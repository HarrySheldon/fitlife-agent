import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../../i18n'
import { api } from '../../services/api'
import { Plan } from '../Plan'
import { NewPlan } from './NewPlan'
import { PlanDetail } from './PlanDetail'

vi.mock('../../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../services/api')>()
  return {
    ...original,
    api: {
      ...original.api,
      listPlans: vi.fn(), getPlan: vi.fn(), createPlanDraft: vi.fn(),
      createPlanAdjustmentDraft: vi.fn(), interpretPlan: vi.fn(), activatePlan: vi.fn(),
    },
  }
})

const generatedPlan = {
  diet_plan: { calories: 2200 }, workout_plan: { days: 4 },
  validation: { passed: true, warnings: [], violations: [], repair_suggestions: [] }, trace: {},
}
const draft = {
  draft_id: 'draft-0000000000000001', created_at: '2026-08-26T09:59:00Z',
  kind: 'deterministic' as const, based_on_plan_id: null, plan: generatedPlan,
}
const stored = {
  plan_id: 'plan-00000001', activated_at: '2026-08-26T10:00:00Z',
  kind: 'deterministic' as const, based_on_plan_id: null, plan: generatedPlan,
}

beforeEach(async () => {
  vi.clearAllMocks()
  await i18n.changeLanguage('en-US')
  vi.mocked(api.listPlans).mockResolvedValue([stored])
  vi.mocked(api.getPlan).mockResolvedValue(stored)
  vi.mocked(api.createPlanDraft).mockResolvedValue(draft)
  vi.mocked(api.createPlanAdjustmentDraft).mockResolvedValue({ ...draft, kind: 'agent_adjusted', based_on_plan_id: stored.plan_id })
  vi.mocked(api.interpretPlan).mockResolvedValue({
    surface: 'plan', action: 'adjust_next_plan', answer_markdown: 'Use the persisted plan.',
    intent: 'plan_adjustment', trace: { active_plan_id: stored.plan_id }, sources: [], model: 'test-model', request_id: 'request-1',
  })
  vi.mocked(api.activatePlan).mockResolvedValue(stored)
})

function renderRoute(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><Routes>
    <Route path="/plan" element={<Plan />} />
    <Route path="/plan/new" element={<NewPlan />} />
    <Route path="/plan/:planId" element={<PlanDetail />} />
  </Routes></MemoryRouter>)
}

describe('plan task routes', () => {
  it('keeps the overview read-only and links plan history and generation', async () => {
    renderRoute('/plan')
    expect(await screen.findByRole('link', { name: /plan-00000001/ })).toHaveAttribute('href', '/plan/plan-00000001')
    expect(screen.getByRole('link', { name: /create plan/i })).toHaveAttribute('href', '/plan/new')
    expect(screen.queryByRole('button', { name: /generate plan/i })).not.toBeInTheDocument()
  })

  it('generates a draft and only activates after explicit confirmation', async () => {
    renderRoute('/plan/new')
    fireEvent.click(screen.getByRole('button', { name: /generate plan/i }))
    expect(await screen.findByText(/ready to use/i)).toBeInTheDocument()
    expect(api.activatePlan).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /confirm and activate/i }))
    await waitFor(() => expect(api.activatePlan).toHaveBeenCalledWith(draft.draft_id))
    expect(await screen.findByRole('heading', { name: /plan-00000001/ })).toBeInTheDocument()
  })

  it('creates an Agent adjustment draft without replacing the active plan until confirmation', async () => {
    renderRoute('/plan/plan-00000001')
    expect(await screen.findByRole('heading', { name: /plan-00000001/ })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/adjustment instructions/i), { target: { value: 'Make Friday lighter' } })
    fireEvent.click(screen.getByRole('button', { name: /generate adjustment draft/i }))
    await waitFor(() => expect(api.createPlanAdjustmentDraft).toHaveBeenCalledWith('plan-00000001', 'Make Friday lighter'))
    expect(api.activatePlan).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /confirm adjusted plan/i }))
    await waitFor(() => expect(api.activatePlan).toHaveBeenCalled())
  })

  it('asks the plan-specific Coach endpoint to interpret the persisted plan', async () => {
    renderRoute('/plan/plan-00000001')
    expect(await screen.findByRole('heading', { name: /plan-00000001/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /open coach/i }))
    const drawer = screen.getByRole('dialog')
    fireEvent.click(within(drawer).getByRole('button', { name: /generate adjustment/i }))

    await waitFor(() => expect(api.interpretPlan).toHaveBeenCalledWith('plan-00000001'))
    expect(await within(drawer).findByText('Use the persisted plan.')).toBeInTheDocument()
  })
})
