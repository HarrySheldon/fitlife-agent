import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import { weeklyAutomationApi } from '../services/weeklyAutomationApi'
import { CoachPage } from './CoachPage'

const chatState = vi.hoisted(() => ({
  send: vi.fn(),
}))

vi.mock('../hooks/useChat', () => ({
  useChat: () => ({
    messages: [],
    loading: false,
    error: null,
    send: chatState.send,
  }),
}))

vi.mock('../hooks/useCoach', () => ({
  useCoach: () => null,
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
  chatState.send.mockResolvedValue(undefined)
  await i18n.changeLanguage('en-US')
})

describe('Coach first-class workbench', () => {
  it('supports session-level read scope toggles, URL prompt handoff, and personalized draft generation', async () => {
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

    // Preloaded URL prompt
    const textarea = screen.getByRole('textbox', { name: 'Ask your coach' })
    expect(textarea).toHaveValue('Analyze my squat progress')

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
})
