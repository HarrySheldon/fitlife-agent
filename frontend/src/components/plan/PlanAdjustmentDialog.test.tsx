import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../../i18n'
import { api } from '../../services/api'
import type { PlanTask } from '../../types'
import { PlanAdjustmentDialog } from './PlanAdjustmentDialog'

vi.mock('../../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../services/api')>()
  return {
    ...original,
    api: {
      ...original.api,
      getCurrentPlan: vi.fn(),
      startPlanTask: vi.fn(),
      decidePlanTaskScope: vi.fn(),
      executePlanTask: vi.fn(),
      confirmPlanTask: vi.fn(),
      cancelPlanTask: vi.fn(),
      getPlanTask: vi.fn(),
      answerPlanTask: vi.fn(),
      listPlanTasks: vi.fn(),
    },
  }
})

const NOW = new Date('2026-10-26T12:00:00Z')

function task(overrides: Partial<PlanTask> = {}): PlanTask {
  return {
    task_id: 'task-1',
    version: 2,
    state: 'generating',
    base_plan_id: 'plan-00000001',
    base_head_revision: 1,
    read_domains: ['training', 'diet'],
    change_domains: ['training', 'diet'],
    repair_rounds: 0,
    rounds_remaining: 2,
    expires_at: '2026-11-20T12:00:00Z',
    missing_constraints: [],
    candidate: null,
    failed_domains: [],
    violations: [],
    ...overrides,
  }
}

const ready = task({
  version: 5,
  state: 'awaiting_confirmation',
  candidate: {
    candidate_id: 'candidate-1',
    digest: 'abcdef0123456789abcdef',
    expires_at: '2026-10-26T12:30:00Z',
    round: 0,
    diff: [{ domain: 'training', path: 'workout_plan.days.0', old_value: 'heavy', new_value: 'light', source: 'validated_candidate' }],
  },
})

beforeEach(async () => {
  sessionStorage.clear()
  vi.clearAllMocks()
  await i18n.changeLanguage('en-US')
  vi.mocked(api.startPlanTask).mockResolvedValue(task({ state: 'collecting', change_domains: ['training'] }))
  vi.mocked(api.getPlanTask).mockResolvedValue(task())
  vi.mocked(api.answerPlanTask).mockResolvedValue(task())
  vi.mocked(api.decidePlanTaskScope).mockResolvedValue(task())
  vi.mocked(api.executePlanTask).mockResolvedValue({ task: ready, answer: null, receipt: null })
  vi.mocked(api.confirmPlanTask).mockResolvedValue({
    task: { ...ready, state: 'activated' },
    plan: {
      plan_id: 'plan-bbbbbbbb', head_revision: 2, activated_at: '2026-10-26T12:05:00Z',
      kind: 'agent_adjusted', based_on_plan_id: 'plan-00000001',
    },
    replayed: false,
  })
  vi.mocked(api.cancelPlanTask).mockResolvedValue({ ...task(), state: 'cancelled' })
  vi.mocked(api.getCurrentPlan).mockResolvedValue({
    plan: {
      plan_id: 'plan-00000001', activated_at: '2026-10-01T00:00:00Z', kind: 'deterministic',
      based_on_plan_id: null,
      plan: { diet_plan: {}, workout_plan: {}, validation: { passed: true, warnings: [], violations: [], repair_suggestions: [] }, trace: {} } as never,
    },
    head_revision: 1,
  })
})

function renderDialog(props: Partial<Parameters<typeof PlanAdjustmentDialog>[0]> = {}) {
  return render(<PlanAdjustmentDialog open onClose={() => {}} planId="plan-00000001" now={NOW} {...props} />)
}

describe('PlanAdjustmentDialog', () => {
  it('retains an unknown creation key across closing and remounting', async () => {
    vi.mocked(api.startPlanTask).mockRejectedValueOnce(new Error('network'))
    const first = renderDialog()
    fireEvent.change(screen.getByLabelText(/adjustment instructions/i), { target: { value: 'Lighter please' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start adjustment' }))
    await screen.findByRole('alert')
    const key = vi.mocked(api.startPlanTask).mock.calls[0][1]
    first.unmount()
    renderDialog()
    fireEvent.change(screen.getByLabelText(/adjustment instructions/i), { target: { value: 'Lighter please' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start adjustment' }))
    await waitFor(() => expect(api.startPlanTask).toHaveBeenCalledTimes(2))
    expect(vi.mocked(api.startPlanTask).mock.calls[1][1]).toBe(key)
  })
  it('restores a referenced task with a read only request', async () => {
    renderDialog({ taskId: 'task-1' })
    await waitFor(() => expect(api.getPlanTask).toHaveBeenCalledWith('task-1'))
    expect(await screen.findByLabelText('Current adjustment request')).toBeInTheDocument()
    expect(api.executePlanTask).not.toHaveBeenCalled()
    expect(api.confirmPlanTask).not.toHaveBeenCalled()
  })

  it('lets the user answer missing movement restrictions', async () => {
    vi.mocked(api.getPlanTask).mockResolvedValue(task({ state: 'awaiting_user_decision', missing_constraints: ['action_restrictions'] }))
    renderDialog({ taskId: 'task-1' })
    fireEvent.change(await screen.findByLabelText('Movement restrictions'), { target: { value: 'No jumping' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm constraints' }))
    await waitFor(() => expect(api.answerPlanTask).toHaveBeenCalledWith('task-1', {
      expected_version: 2, answers: { action_restrictions: ['No jumping'] },
    }, expect.any(String)))
  })

  it('uses a new opaque creation key after remounting', async () => {
    const first = renderDialog()
    fireEvent.change(screen.getByLabelText(/adjustment instructions/i), { target: { value: 'Make it lighter' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start adjustment' }))
    await waitFor(() => expect(api.startPlanTask).toHaveBeenCalledTimes(1))
    const key = vi.mocked(api.startPlanTask).mock.calls[0][1]
    first.unmount(); sessionStorage.clear()
    renderDialog()
    fireEvent.change(screen.getByLabelText(/adjustment instructions/i), { target: { value: 'Make it lighter' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start adjustment' }))
    await waitFor(() => expect(api.startPlanTask).toHaveBeenCalledTimes(2))
    expect(vi.mocked(api.startPlanTask).mock.calls[1][1]).not.toBe(key)
    expect(key).not.toContain('lighter')
  })

  it('starts a task, asks for the missing permission, then executes and confirms', async () => {
    renderDialog()
    fireEvent.change(screen.getByLabelText(/adjustment instructions/i),
                     { target: { value: 'Make Friday lighter' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start adjustment' }))

    await waitFor(() => expect(api.startPlanTask).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.startPlanTask).mock.calls[0][0]).toMatchObject({
      base_plan_id: 'plan-00000001',
      read_domains: ['training', 'diet'],
      change_domains: ['training', 'diet'],
      instructions: 'Make Friday lighter',
    })
    // The task came back asking for the diet grant; nothing has been generated.
    expect(await screen.findByRole('button', { name: 'Allow' })).toBeInTheDocument()
    expect(api.executePlanTask).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Allow' }))
    await waitFor(() => expect(api.decidePlanTaskScope).toHaveBeenCalledWith(
      'task-1',
      expect.objectContaining({ expected_version: 2, decision: 'allow', change_domains: ['training', 'diet'] }),
      expect.any(String),
    ))
    expect(api.confirmPlanTask).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Generate candidate' }))
    await waitFor(() => expect(api.executePlanTask).toHaveBeenCalledTimes(1))
    expect(api.confirmPlanTask).not.toHaveBeenCalled()

    fireEvent.click(await screen.findByRole('button', { name: 'Confirm and activate' }))
    await waitFor(() => expect(api.confirmPlanTask).toHaveBeenCalledWith(
      'task-1',
      expect.objectContaining({
        expected_version: 5, expected_head_revision: 1, candidate_digest: 'abcdef0123456789abcdef',
      }),
      expect.any(String),
    ))
  })

  it('reports the new plan once it is confirmed', async () => {
    const onConfirmed = vi.fn()
    renderDialog({ onConfirmed })
    fireEvent.change(screen.getByLabelText(/adjustment instructions/i), { target: { value: 'Change it' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start adjustment' }))
    await screen.findByRole('button', { name: 'Allow' })
    fireEvent.click(screen.getByRole('button', { name: 'Allow' }))
    await waitFor(() => expect(api.decidePlanTaskScope).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: 'Generate candidate' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm and activate' }))

    await waitFor(() => expect(onConfirmed).toHaveBeenCalledWith('plan-bbbbbbbb'))
    expect(await screen.findByText(/plan-bbbbbbbb is now the active plan/i)).toBeInTheDocument()
  })

  it('keeps what the model said apart from what the validator refused', async () => {
    // A sentence about what changed is not evidence that anything valid did, so
    // the two are rendered as separate panels rather than one reassuring block.
    vi.mocked(api.executePlanTask).mockResolvedValue({
      task: task({
        state: 'repairing',
        failed_domains: ['diet'],
        violations: [{ code: 'CONSTRAINT_VIOLATION', domain: 'diet', path: 'diet_plan.meals' }],
      }),
      answer: 'I fixed the training days.',
      receipt: null,
    })
    renderDialog()
    fireEvent.change(screen.getByLabelText(/adjustment instructions/i), { target: { value: 'Change it' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start adjustment' }))
    await screen.findByRole('button', { name: 'Allow' })
    fireEvent.click(screen.getByRole('button', { name: 'Allow' }))
    await waitFor(() => expect(api.decidePlanTaskScope).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: 'Generate candidate' }))

    expect(await screen.findByText('What the model said')).toBeInTheDocument()
    expect(screen.getByText('I fixed the training days.')).toBeInTheDocument()
    expect(screen.getByText('CONSTRAINT_VIOLATION')).toBeInTheDocument()
    expect(screen.getByText('Validation failures')).toBeInTheDocument()
  })

  it('never executes or confirms on its own, however often it is reopened', async () => {
    // Opening the dialog, receiving a task, and re-rendering are all free. Only a
    // click may spend a model call or write history.
    const { rerender } = renderDialog()
    fireEvent.change(screen.getByLabelText(/adjustment instructions/i), { target: { value: 'Change it' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start adjustment' }))
    await screen.findByRole('button', { name: 'Allow' })
    rerender(<PlanAdjustmentDialog open onClose={() => {}} planId="plan-00000001" now={NOW} />)
    rerender(<PlanAdjustmentDialog open={false} onClose={() => {}} planId="plan-00000001" now={NOW} />)
    rerender(<PlanAdjustmentDialog open onClose={() => {}} planId="plan-00000001" now={NOW} />)

    expect(api.executePlanTask).not.toHaveBeenCalled()
    expect(api.confirmPlanTask).not.toHaveBeenCalled()
    await waitFor(() => expect(api.getPlanTask).toHaveBeenCalledWith('task-1'))
  })

  it('reuses the same key when a failed attempt is retried', async () => {
    // An unknown network result must not turn into a second request the server
    // refuses as a version conflict.
    vi.mocked(api.startPlanTask)
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce(task())
    renderDialog()
    fireEvent.change(screen.getByLabelText(/adjustment instructions/i), { target: { value: 'Change it' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start adjustment' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('network')
    fireEvent.click(screen.getByRole('button', { name: 'Start adjustment' }))
    await waitFor(() => expect(api.startPlanTask).toHaveBeenCalledTimes(2))

    const first = vi.mocked(api.startPlanTask).mock.calls[0][1]
    const second = vi.mocked(api.startPlanTask).mock.calls[1][1]
    expect(second).toBe(first)
  })

  it('resolves the base plan from the server when no id is given', async () => {
    renderDialog({ planId: undefined })
    fireEvent.change(screen.getByLabelText(/adjustment instructions/i), { target: { value: 'Change it' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start adjustment' }))

    await waitFor(() => expect(api.getCurrentPlan).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(api.startPlanTask).toHaveBeenCalledWith(
      expect.objectContaining({ base_plan_id: 'plan-00000001' }), expect.any(String)))
  })
})
