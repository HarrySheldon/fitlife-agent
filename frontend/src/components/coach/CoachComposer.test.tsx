import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import '../../i18n'
import { CoachComposer } from './CoachComposer'

it('does not send Enter during IME composition and sends once afterwards', () => {
  const send = vi.fn()
  render(<CoachComposer value="今天怎么样" onChange={vi.fn()} onSend={send} disabled={false} />)
  const input = screen.getByRole('textbox')
  fireEvent.compositionStart(input)
  fireEvent.keyDown(input, { key: 'Enter', isComposing: true })
  expect(send).not.toHaveBeenCalled()
  fireEvent.compositionEnd(input)
  fireEvent.keyDown(input, { key: 'Enter' })
  expect(send).toHaveBeenCalledTimes(1)
})

it('preserves Shift+Enter and blocks sending while another turn owns the slot', () => {
  const send = vi.fn()
  const view = render(<CoachComposer value="Question" onChange={vi.fn()} onSend={send} disabled={false} />)
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter', shiftKey: true })
  expect(send).not.toHaveBeenCalled()
  view.rerender(<CoachComposer value="Question" onChange={vi.fn()} onSend={send} disabled />)
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' })
  expect(send).not.toHaveBeenCalled()
  expect(screen.getByRole('button')).toBeDisabled()
})
