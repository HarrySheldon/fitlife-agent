import { render, screen } from '@testing-library/react'
import { beforeEach, expect, it } from 'vitest'

import i18n from '../../i18n'
import { CoachMessages } from './CoachMessages'

beforeEach(async () => { await i18n.changeLanguage('en-US') })

const message = {
  message_id: 'm1', turn_id: 't1', role: 'coach' as const, body: 'Answer',
  created_at: '2026-10-19T00:00:00Z',
}

it('renders a business task reference as read-only text', () => {
  render(<CoachMessages conversation="c1" messages={[{
    ...message,
    metadata: { business_task_ref: { kind: 'plan_adjustment', task_id: 'task-123' } },
  }]} />)
  const reference = screen.getByTestId('coach-business-task')
  expect(reference).toHaveTextContent('Linked business task: plan_adjustment · task-123')
  expect(reference.querySelector('button, a')).toBeNull()
})

it('does not invent a business task reference when none was handed over', () => {
  render(<CoachMessages conversation="c1" messages={[message]} />)
  expect(screen.queryByTestId('coach-business-task')).not.toBeInTheDocument()
})
