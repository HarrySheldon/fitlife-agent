import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import i18n from '../../i18n'
import { CoachProvider } from '../../hooks/useCoach'
import { CoachWindow } from './CoachWindow'

const api = vi.hoisted(() => ({ list: vi.fn(), messages: vi.fn(), active: vi.fn(), create: vi.fn(), send: vi.fn(), turn: vi.fn(), cancel: vi.fn() }))
vi.mock('../../services/coachApi', () => ({ coachApi: api }))
beforeEach(async () => {
  vi.clearAllMocks()
  sessionStorage.clear()
  await i18n.changeLanguage('en-US')
  api.list.mockResolvedValue({ conversations: [] })
  api.messages.mockResolvedValue({ messages: [] })
  api.active.mockResolvedValue({ turn: null })
  api.turn.mockResolvedValue({ turn_id: 't1', conversation_id: 'c1', status: 'succeeded', stopping: false, error_code: null, receipt: null })
})

it('shows sources and date by default while keeping technical metadata collapsed', async () => {
  api.list.mockResolvedValue({ conversations: [{ conversation_id: 'c1', title: 'Saved' }] })
  api.messages.mockResolvedValue({ messages: [{ message_id: 'm1', turn_id: 't1', role: 'coach', body: 'Reviewed advice', created_at: '2026-10-19T00:00:00Z',
    metadata: { context: { date: '2026-10-19' }, sources: [{ source: 'kb', heading: 'Nutrition source' }], model: 'test-model' } }] })
  render(<CoachProvider owner="test"><CoachWindow /></CoachProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'Coach' }))
  expect(await screen.findByText('Nutrition source')).toBeVisible()
  expect(screen.getByText(/2026-10-19/)).toBeVisible()
  expect(screen.getByText(/test-model/).closest('details')).not.toHaveAttribute('open')
  expect(api.send).not.toHaveBeenCalled()
})

it('has a centered non-modal dialog, and opening/resizing/minimizing do not call the model', async () => {
  render(<CoachProvider owner="test"><CoachWindow /></CoachProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'Coach' }))
  const dialog = screen.getByRole('dialog', { name: 'Coach' })
  expect(dialog).not.toHaveAttribute('aria-modal', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Toggle maximize' }))
  expect(dialog).toHaveClass('coach-window-maximized')
  fireEvent.keyDown(dialog, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Coach' }))
  expect(api.send).not.toHaveBeenCalled()
  expect(api.cancel).not.toHaveBeenCalled()
  await waitFor(() => expect(api.list).toHaveBeenCalledTimes(1))
})

it('keeps the unsent draft when minimized and never renders model text as HTML', async () => {
  api.list.mockResolvedValue({ conversations: [{ conversation_id: 'c1', title: 'Today' }] })
  api.messages.mockResolvedValue({ messages: [{ message_id: 'm1', turn_id: 't1', role: 'coach', body: '<script>bad()</script>Safe text', created_at: '2026-10-19T00:00:00Z' }] })
  const { container } = render(<CoachProvider owner="test"><CoachWindow /></CoachProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'Coach' }))
  await screen.findByRole('heading', { name: 'Today' })
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Keep my question' } })
  fireEvent.click(screen.getByRole('button', { name: 'Minimize coach' }))
  fireEvent.click(screen.getByRole('button', { name: 'Coach' }))
  expect(screen.getByRole('textbox')).toHaveValue('Keep my question')
  expect(container.querySelector('script')).toBeNull()
})

it('retries only after an explicit click and reconstructs saved-object fields without server policy flags', async () => {
  api.list.mockResolvedValue({ conversations: [{ conversation_id: 'c1', title: 'Saved plan' }] })
  api.messages.mockResolvedValue({ messages: [{ message_id: 'm1', turn_id: 't1', role: 'user', body: 'Explain saved plan', created_at: '2026-10-19T00:00:00Z' }] })
  api.turn.mockResolvedValue({ turn_id: 't1', conversation_id: 'c1', status: 'failed', stopping: false, error_code: 'SAFE_ERROR',
    receipt: { context: { action: 'adjust_next_plan', surface: 'plan', plan_id: 'plan-12345678', language: 'en-US', answer_mode: 'brief', admitted_scope: true } } })
  api.send.mockResolvedValue({ turn_id: 't2', conversation_id: 'c1', status: 'running', stopping: false, error_code: null, receipt: null })
  render(<CoachProvider owner="retry"><CoachWindow /></CoachProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'Coach' }))
  const retry = await screen.findByRole('button', { name: /Retry/ })
  expect(api.send).not.toHaveBeenCalled()
  fireEvent.click(retry)
  await waitFor(() => expect(api.send).toHaveBeenCalledTimes(1))
  const payload = api.send.mock.calls[0][1]
  expect(payload).toMatchObject({ question: 'Explain saved plan', action: 'adjust_next_plan', surface: 'plan', plan_id: 'plan-12345678' })
  expect(payload).not.toHaveProperty('admitted_scope')
})
