import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../../i18n'
import type { PlanTask } from '../../types'
import { PlanTaskCard } from './PlanTaskCard'

const NOW = new Date('2026-10-26T12:00:00Z')

function task(overrides: Partial<PlanTask> = {}): PlanTask {
  return {
    task_id: 'task-1',
    version: 4,
    state: 'awaiting_confirmation',
    base_plan_id: 'plan-00000001',
    base_head_revision: 1,
    read_domains: ['training', 'diet'],
    change_domains: ['training', 'diet'],
    repair_rounds: 1,
    rounds_remaining: 1,
    expires_at: '2026-11-20T12:00:00Z',
    missing_constraints: [],
    candidate: {
      candidate_id: 'candidate-1',
      digest: 'abcdef0123456789abcdef',
      expires_at: '2026-10-26T12:30:00Z',
      round: 1,
    },
    failed_domains: [],
    violations: [],
    ...overrides,
  }
}

beforeEach(async () => {
  await i18n.changeLanguage('en-US')
})

describe('PlanTaskCard', () => {
  it('never presents a read-only domain as changed', () => {
    // The model may read the diet to reason about training. It was not allowed to
    // change it, so the card must not say it did.
    render(<PlanTaskCard task={task({ change_domains: ['training'] })} now={NOW} />)

    const training = screen.getByText('Training').closest('.plan-task-domain') as HTMLElement
    const diet = screen.getByText('Diet').closest('.plan-task-domain') as HTMLElement

    expect(within(training).getByText('May be changed')).toBeInTheDocument()
    expect(within(diet).getByText('Read only')).toBeInTheDocument()
    expect(within(diet).queryByText('May be changed')).not.toBeInTheDocument()
    expect(screen.getAllByText('May be changed')).toHaveLength(1)
  })

  it('offers confirmation only for a candidate that passed and has not expired', () => {
    const onConfirm = vi.fn()
    render(<PlanTaskCard task={task()} onConfirm={onConfirm} now={NOW} />)

    const confirm = screen.getByRole('button', { name: 'Confirm and activate' })
    expect(confirm).toBeEnabled()
    fireEvent.click(confirm)
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('withholds confirmation from a candidate that did not pass', () => {
    render(<PlanTaskCard task={task({ failed_domains: ['diet'] })} now={NOW} />)

    expect(screen.getByText('This candidate did not pass validation.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm and activate' })).toBeDisabled()
  })

  it('withholds confirmation once the candidate has expired, and says when', () => {
    render(<PlanTaskCard task={task()} now={new Date('2026-10-26T12:31:00Z')} />)

    expect(screen.getByRole('button', { name: 'Confirm and activate' })).toBeDisabled()
    expect(screen.getByText(/candidate expired 2026-10-26T12:30:00Z/i)).toBeInTheDocument()
  })

  it('shows the round budget, the expiry and what the task still needs', () => {
    render(<PlanTaskCard
      task={task({ missing_constraints: ['constraints.action_restrictions'] })}
      now={NOW} />)

    expect(screen.getByText('1 of 2 repair rounds used, 1 left')).toBeInTheDocument()
    expect(screen.getByText(/task expires 2026-11-20/i)).toBeInTheDocument()
    expect(screen.getByText('constraints.action_restrictions')).toBeInTheDocument()
  })

  it('asks for the missing permission instead of generating on its own', () => {
    const onAllow = vi.fn()
    const onDeny = vi.fn()
    render(<PlanTaskCard
      task={task({ state: 'collecting', change_domains: ['training'], candidate: null })}
      onAllowScope={onAllow} onDenyScope={onDeny} now={NOW} />)

    fireEvent.click(screen.getByRole('button', { name: 'Allow' }))
    fireEvent.click(screen.getByRole('button', { name: 'Keep read only' }))

    expect(onAllow).toHaveBeenCalledTimes(1)
    expect(onDeny).toHaveBeenCalledTimes(1)
  })

  it('lists validation failures by code and path', () => {
    render(<PlanTaskCard
      task={task({ violations: [{ code: 'CONSTRAINT_VIOLATION', domain: 'diet', path: 'diet_plan.meals' }] })}
      now={NOW} />)

    expect(screen.getByText('CONSTRAINT_VIOLATION')).toBeInTheDocument()
    expect(screen.getByText('diet_plan.meals')).toBeInTheDocument()
  })

  it('does not offer to cancel a task that already ended', () => {
    render(<PlanTaskCard task={task({ state: 'activated' })} now={NOW} />)

    expect(screen.queryByRole('button', { name: 'Cancel task' })).not.toBeInTheDocument()
  })
})
