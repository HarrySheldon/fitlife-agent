import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import { api } from '../services/api'
import { weeklyAutomationApi } from '../services/weeklyAutomationApi'
import { CoachPage } from './CoachPage'

const chatState = vi.hoisted(() => ({
  messages: [] as Array<{ id: string; role: 'user' | 'agent'; content: string; createdAt: string; model?: string }>,
  loading: false,
  error: null as string | null,
  lastFailedQuestion: null as string | null,
  send: vi.fn(),
  stop: vi.fn(),
  clear: vi.fn(),
}))

const coachState = vi.hoisted(() => ({
  value: null as Record<string, unknown> | null,
}))

vi.mock('../hooks/useChat', () => ({
  useChat: () => chatState,
}))

vi.mock('../hooks/useCoach', () => ({
  useCoach: () => coachState.value,
}))

vi.mock('../services/weeklyAutomationApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/weeklyAutomationApi')>()
  return {
    ...original,
    weeklyAutomationApi: {
      ...original.weeklyAutomationApi,
      generatePersonalizedDraft: vi.fn(),
    },
  }
})

beforeEach(async () => {
  vi.clearAllMocks()
  chatState.messages = []
  chatState.loading = false
  chatState.error = null
  chatState.lastFailedQuestion = null
  chatState.send.mockResolvedValue(true)
  coachState.value = null
  vi.spyOn(api, 'modelWorkspace').mockResolvedValue({
    revision: 1,
    active: {
      provider: 'custom',
      provider_id: 'deepseek',
      protocol: 'chat_completions',
      base_url: 'https://api.deepseek.com/v1',
      model: 'deepseek-chat',
      enabled: true,
      api_key_configured: true,
      api_key_hint: 'sk-***1234',
      test_status: 'success',
      test_error_code: null,
      tested_at: '2026-11-20T00:00:00Z',
      updated_at: '2026-11-20T00:00:00Z',
      state: 'success',
    },
    draft: null,
  })
  await i18n.changeLanguage('en-US')
})

describe('Coach first-class workbench (UX-2)', () => {
  it('supports session-level read scope toggles, URL prompt handoff, IME guard, and personalized draft generation', async () => {
    vi.mocked(weeklyAutomationApi.generatePersonalizedDraft).mockResolvedValue({
      cycle: {
        id: 'cycle-new',
        title: '2026-W47 Personalized Block',
        goal_type: 'fat_loss',
        start_date: '2026-11-16',
        duration_weeks: 4,
        phases: [],
        status: 'draft',
        source: 'agent',
        rationale: {},
        version: 1,
        created_at: '2026-11-20T00:00:00Z',
        updated_at: '2026-11-20T00:00:00Z',
        activated_at: null,
      },
      week1_days: [],
    })

    render(
      <MemoryRouter initialEntries={['/coach?surface=progress&prompt=Analyze+my+squat+progress']}>
        <CoachPage />
      </MemoryRouter>,
    )

    // Active model badge displays with switch link
    expect(await screen.findByText('deepseek-chat')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Switch' })).toHaveAttribute('href', '/settings/model?returnTo=/coach')

    // Preloaded URL prompt
    const textarea = screen.getByRole('textbox', { name: 'Ask your coach' })
    expect(textarea).toHaveValue('Analyze my squat progress')

    // IME composition protects Enter from prematurely sending
    fireEvent.compositionStart(textarea)
    fireEvent.keyDown(textarea, { key: 'Enter', isComposing: true })
    expect(chatState.send).not.toHaveBeenCalled()
    fireEvent.compositionEnd(textarea)

    // Session-level read scope toggles work cleanly
    const dietToggle = screen.getByRole('button', { name: /Diet logs/ })
    expect(dietToggle).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(dietToggle)
    expect(dietToggle).toHaveAttribute('aria-pressed', 'false')

    // Generate personalized plan draft (never auto-activates; links to /plan to confirm)
    fireEvent.click(screen.getByRole('button', { name: /Generate personalized plan draft/ }))
    expect(await screen.findByText(/Draft created: 2026-W47 Personalized Block/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Review plan draft/ })).toHaveAttribute('href', '/plan')

    // Sending question forwards to chat handler
    fireEvent.click(screen.getByRole('button', { name: /Send/ }))
    await waitFor(() => {
      expect(chatState.send).toHaveBeenCalledWith('Analyze my squat progress')
    })
  })

  it('preserves user input when sending fails and shows unconfigured model guide banner', async () => {
    vi.spyOn(api, 'modelWorkspace').mockResolvedValue({ revision: 0, active: null, draft: null })
    chatState.send.mockResolvedValue(false)

    render(
      <MemoryRouter initialEntries={['/coach']}>
        <CoachPage />
      </MemoryRouter>,
    )

    const configLink = await screen.findByRole('link', { name: /Configure model/ })
    expect(configLink).toHaveAttribute('href', '/settings/model?returnTo=/coach')

    // Clicking a starter while unconfigured fills the composer instead of firing an error request
    fireEvent.click(screen.getByRole('button', { name: /Analyze recent progress/ }))
    const textarea = screen.getByRole('textbox', { name: 'Ask your coach' })
    expect((textarea as HTMLTextAreaElement).value).toContain('weight trend')
    expect(chatState.send).not.toHaveBeenCalled()

    // Explicitly sending when send fails keeps input intact
    fireEvent.change(textarea, { target: { value: 'Keep my typed text on error' } })
    fireEvent.click(screen.getByRole('button', { name: /Send/ }))
    await waitFor(() => expect(chatState.send).toHaveBeenCalledWith('Keep my typed text on error'))
    expect(textarea).toHaveValue('Keep my typed text on error')
  })

  it('requires confirmation modal before deleting a conversation and supports generating plan draft from an answer', async () => {
    const remove = vi.fn().mockResolvedValue(undefined)
    const rename = vi.fn().mockResolvedValue(undefined)
    coachState.value = {
      open: false,
      setOpen: vi.fn(),
      maximized: false,
      setMaximized: vi.fn(),
      conversations: [
        {
          conversation_id: 'c1',
          title: 'Knee-friendly squat swaps',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
      selected: 'c1',
      setSelected: vi.fn(),
      messages: [
        {
          message_id: 'm1',
          turn_id: 't1',
          role: 'coach',
          body: 'Use goblet box squat and leg press while knee recovers.',
          created_at: new Date().toISOString(),
        },
      ],
      draft: '',
      setDraft: vi.fn(),
      readDomains: ['profile', 'training', 'diet'],
      toggleReadDomain: vi.fn(),
      active: null,
      lastTurn: null,
      error: false,
      notice: '',
      unread: false,
      clearUnread: vi.fn(),
      sending: false,
      supportsReadConsent: true,
      capabilitiesReady: true,
      show: vi.fn(),
      newChat: vi.fn(),
      send: vi.fn().mockResolvedValue(true),
      stop: vi.fn(),
      remove,
      rename,
    }
    vi.mocked(weeklyAutomationApi.generatePersonalizedDraft).mockResolvedValue({
      cycle: {
        id: 'cycle-from-answer',
        title: 'Knee-Safe Block',
        goal_type: 'fat_loss',
        start_date: '2026-11-23',
        duration_weeks: 4,
        phases: [],
        status: 'draft',
        source: 'agent',
        rationale: {},
        version: 1,
        created_at: '2026-11-20T00:00:00Z',
        updated_at: '2026-11-20T00:00:00Z',
        activated_at: null,
      },
      week1_days: [],
    })

    render(
      <MemoryRouter initialEntries={['/coach']}>
        <CoachPage />
      </MemoryRouter>,
    )

    // Delete icon opens confirmation modal instead of deleting immediately
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(remove).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: 'Delete this chat?' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Stop and delete' }))
    await waitFor(() => expect(remove).toHaveBeenCalledWith('c1'))

    // Generate plan draft from specific coach reply passes focus_note
    fireEvent.click(screen.getByRole('button', { name: /Generate plan draft from this/ }))
    await waitFor(() => {
      expect(weeklyAutomationApi.generatePersonalizedDraft).toHaveBeenCalledWith(
        expect.objectContaining({
          duration_weeks: 4,
          focus_note: expect.stringContaining('goblet box squat'),
        }),
      )
    })
    expect(await screen.findByText(/Draft created: Knee-Safe Block/)).toBeInTheDocument()
  })
})
