import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef, useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import { api } from '../services/api'
import { CoachDrawer } from './CoachDrawer'

vi.mock('../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/api')>()
  return { ...original, api: { ...original.api, coachAction: vi.fn() } }
})

const answer = {
  surface: 'plan' as const,
  action: 'adjust_next_plan' as const,
  answer_markdown: 'Keep the active plan stable.',
  intent: 'plan', trace: {}, sources: [], model: 'configured', request_id: 'request-1',
}

function Harness() {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('Make Friday lighter')
  const triggerRef = useRef<HTMLButtonElement>(null)
  return <>
    <label>Adjustment instructions<input value={draft} onChange={(event) => setDraft(event.target.value)} /></label>
    <button ref={triggerRef} type="button" onClick={() => setOpen(true)}>Open Coach</button>
    <CoachDrawer
      open={open}
      onClose={() => setOpen(false)}
      returnFocusRef={triggerRef}
      surface="plan"
      question="Plan ID: plan-00000001"
      actions={[{ action: 'adjust_next_plan', label: 'Suggest adjustment' }]}
    />
  </>
}

describe('CoachDrawer', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    await i18n.changeLanguage('en-US')
    vi.mocked(api.coachAction).mockResolvedValue(answer)
  })

  it('is a modal dialog with Escape, backdrop, close and focus behavior', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const trigger = screen.getByRole('button', { name: 'Open Coach' })
    await user.click(trigger)
    const dialog = screen.getByRole('dialog', { name: 'Coach' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Suggest adjustment' })).toHaveFocus())

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()

    await user.click(trigger)
    await user.click(screen.getByRole('button', { name: 'Close Coach' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await user.click(trigger)
    fireEvent.mouseDown(screen.getByTestId('coach-drawer-backdrop'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('traps Tab focus across the current drawer controls', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Open Coach' }))

    const close = screen.getByRole('button', { name: 'Close Coach' })
    const action = screen.getByRole('button', { name: 'Suggest adjustment' }) as HTMLButtonElement
    action.focus()
    fireEvent.keyDown(document, { key: 'Tab' })
    expect(close).toHaveFocus()

    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(action).toHaveFocus()
  })

  it('keeps focus inside when an unrelated parent render changes the onClose callback identity', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Open Coach' }))
    const action = screen.getByRole('button', { name: 'Suggest adjustment' })
    await waitFor(() => expect(action).toHaveFocus())

    fireEvent.change(screen.getByLabelText('Adjustment instructions'), { target: { value: 'Unrelated rerender' } })

    expect(action).toHaveFocus()
    expect(screen.getByRole('dialog')).toContainElement(document.activeElement as HTMLElement)
  })

  it('does not include hidden, inert, aria-hidden, disabled or CSS-invisible controls in the focus loop', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Open Coach' }))
    const close = screen.getByRole('button', { name: 'Close Coach' })
    const action = screen.getByRole('button', { name: 'Suggest adjustment' }) as HTMLButtonElement
    const panel = action.closest('.coach-panel') as HTMLElement

    for (const hide of [
      () => { action.hidden = true },
      () => { action.hidden = false; panel.setAttribute('inert', '') },
      () => { panel.removeAttribute('inert'); panel.setAttribute('aria-hidden', 'true') },
      () => { panel.removeAttribute('aria-hidden'); panel.style.display = 'none' },
      () => { panel.style.display = ''; action.disabled = true },
    ]) {
      hide()
      close.focus()
      fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
      expect(close).toHaveFocus()
    }
  })

  it('keeps page form state while isolating request state and route context between openings', async () => {
    const user = userEvent.setup()
    let resolveFirst!: (value: typeof answer) => void
    vi.mocked(api.coachAction).mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
    render(<Harness />)

    const input = screen.getByLabelText('Adjustment instructions')
    await user.clear(input)
    await user.type(input, 'Preserve this page draft')
    await user.click(screen.getByRole('button', { name: 'Open Coach' }))
    await user.click(screen.getByRole('button', { name: 'Suggest adjustment' }))
    expect(api.coachAction).toHaveBeenCalledWith({
      surface: 'plan', action: 'adjust_next_plan', question: 'Plan ID: plan-00000001',
    })
    expect(screen.getByText('Thinking...')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Close Coach' }))
    expect(input).toHaveValue('Preserve this page draft')
    await user.click(screen.getByRole('button', { name: 'Open Coach' }))
    expect(screen.getByText(/choose an action/i)).toBeInTheDocument()
    expect(screen.queryByText('Thinking...')).not.toBeInTheDocument()

    await act(async () => resolveFirst(answer))
    expect(screen.queryByText(answer.answer_markdown)).not.toBeInTheDocument()
  })
})
