import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { smartEntryApi } from '../services/smartEntryApi'
import { clearSmartEntryRecovery } from '../services/smartEntryRecovery'
import type { SmartCandidate, SmartEntryDraft } from '../types/smartEntry'
import { SmartEntry } from './SmartEntry'

const auth = vi.hoisted(() => ({ owner: 'user-1' }))
vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ user: { user_id: auth.owner } }) }))
vi.mock('../services/smartEntryApi', () => ({ smartEntryApi: {
  capabilities: vi.fn(), findLatestDraft: vi.fn(), getDraft: vi.fn(), createDraft: vi.fn(),
  updateDraft: vi.fn(), deleteDraft: vi.fn(), analyzeDraft: vi.fn(), confirmDraft: vi.fn(),
  startInteraction: vi.fn(), answerInteraction: vi.fn(), correctInteraction: vi.fn(), confirmItems: vi.fn(),
} }))

function fixture(owner = 'user-1'): SmartEntryDraft {
  const food: SmartCandidate = {
    id: 'oats', kind: 'food', raw_text: 'Oats', normalized_text: 'Oats', subject_text: 'Oats',
    meal_context: 'breakfast', selected: true, selected_catalog_id: null, catalog_choices: [],
    issues: [], provenance: {}, assumptions: [], agent_estimate_accepted: false,
    values: { name: 'Oats', amount: 100, unit: 'g', intake_ratio: 1, calories: 200, carbs: 20, protein: 10, fat: 4, basis_type: 'per_100g' },
  }
  return {
    id: 'mixed-task', user_id: owner, version: 2,
    payload: { log_date: '2026-07-26', raw_text: 'Oats and squat', parser_version: 'v1', candidates: [food,
      { ...food, id: 'squat', kind: 'strength', raw_text: 'Squat', normalized_text: 'Squat', subject_text: 'Squat',
        meal_context: null, selected_catalog_id: 'squat-catalog', issues: ['SMART_ENTRY_STRENGTH_VOLUME_REQUIRED'],
        values: { name: 'Squat', primary_muscle: 'legs', set_count: 3, reps: null, load_kg: 60 } }],
      interaction: { schema_version: 2, active: true, clarification_rounds: 1, status: 'awaiting_confirmation',
        items: [{ item_id: 'oats', revision: 1, state: 'ready', values: food.values, sources: { calories: 'user_provided' }, assumptions: [], missing_fields: [] }],
        question_groups: [{ group_id: 'portion', expected_version: 2, asked_at: '2026-07-26T00:00:00Z', answered: false,
          questions: [{ item_id: 'oats', field: 'amount', portion_options: ['100'] }] }] } },
    agent_status: 'not_requested', agent_prompt_version: null, agent_model: null, agent_metadata: {},
    item_commits: [], dependency_validity: [], expires_at: '2027-01-01T00:00:00Z',
    created_at: '2026-07-26T00:00:00Z', updated_at: '2026-07-26T00:00:00Z',
  }
}
function page() { return <MemoryRouter initialEntries={['/today/smart-entry?date=2026-07-26']}><SmartEntry /></MemoryRouter> }
async function editReps() {
  const reps = await screen.findByLabelText('Repetitions per set')
  await waitFor(() => expect(reps).toBeEnabled())
  fireEvent.change(reps, { target: { value: '8' } })
}
beforeEach(async () => {
  auth.owner = 'user-1'
  Object.values(smartEntryApi).forEach((method) => vi.mocked(method).mockReset())
  localStorage.clear()
  await i18n.changeLanguage('en-US')
  vi.mocked(smartEntryApi.capabilities).mockResolvedValue({ interactive_entry_enabled: true, entry_task_ttl_days: 30 })
  vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue(fixture())
})

describe('local training edits across food commands with the real draft hook', () => {
  it.each(['correction', 'answer', 'save'] as const)('retains unsaved reps after a successful food %s without saving training', async (command) => {
    const next = fixture()
    next.version = 3
    next.payload.candidates[0].values.amount = 50
    next.payload.interaction!.items[0].values = { ...next.payload.candidates[0].values }
    next.payload.interaction!.items[0].revision = 2
    next.payload.interaction!.question_groups[0].answered = true
    vi.mocked(smartEntryApi.correctInteraction).mockResolvedValue(next)
    vi.mocked(smartEntryApi.answerInteraction).mockResolvedValue(next)
    vi.mocked(smartEntryApi.confirmItems).mockResolvedValue({ draft_id: next.id, commits: [], remaining_draft_version: 3, replayed: false })
    if (command === 'save') next.payload.interaction!.items[0].state = 'saved'
    vi.mocked(smartEntryApi.getDraft).mockResolvedValue(next)
    if (command === 'answer') {
      const initial = fixture()
      initial.payload.candidates[0].values.amount = null
      initial.payload.interaction!.items[0].values.amount = null
      initial.payload.interaction!.items[0].state = 'needs_clarification'
      initial.payload.interaction!.items[0].missing_fields = ['amount']
      vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue(initial)
    }
    render(page())
    await editReps()
    if (command === 'correction') {
      const oats = screen.getByRole('article', { name: 'Oats' })
      fireEvent.change(within(oats).getByLabelText('Observed portion amount'), { target: { value: '50' } })
      fireEvent.click(within(oats).getByRole('button', { name: 'Apply item corrections' }))
      await waitFor(() => expect(smartEntryApi.correctInteraction).toHaveBeenCalledOnce())
    } else if (command === 'answer') {
      const panel = screen.getByRole('region', { name: 'Food clarification' })
      fireEvent.click(within(panel).getByLabelText('I don’t know'))
      fireEvent.click(within(panel).getByRole('button', { name: 'Submit answers' }))
      await waitFor(() => expect(smartEntryApi.answerInteraction).toHaveBeenCalledOnce())
    } else {
      fireEvent.click(screen.getByLabelText('Select Oats to save'))
      fireEvent.click(screen.getByRole('button', { name: 'Save selected food items' }))
      await screen.findByText('Saved')
    }
    await waitFor(() => expect(screen.getByLabelText('Repetitions per set')).toBeEnabled())
    expect(screen.getByLabelText('Repetitions per set')).toHaveValue(8)
    expect(within(screen.getByRole('article', { name: 'Oats' })).getByLabelText('Observed portion amount')).toHaveValue(50)
    expect(smartEntryApi.updateDraft).not.toHaveBeenCalled()
    expect(smartEntryApi.confirmDraft).not.toHaveBeenCalled()
  })

  it('drops local training edits when logout clears the draft', async () => {
    render(page())
    await editReps()
    await act(async () => { clearSmartEntryRecovery('user-1') })
    expect(screen.queryByLabelText('Repetitions per set')).not.toBeInTheDocument()
    expect(smartEntryApi.updateDraft).not.toHaveBeenCalled()
  })

  it('keeps conflicting local reps visible and blocks confirmation when server training changed', async () => {
    const next = fixture()
    next.version = 3
    next.payload.candidates[1].values.reps = 12
    next.payload.candidates[1].issues = []
    vi.mocked(smartEntryApi.correctInteraction).mockResolvedValue(next)
    render(page())
    await editReps()
    const oats = screen.getByRole('article', { name: 'Oats' })
    await waitFor(() => expect(within(oats).getByLabelText('Observed portion amount')).toBeEnabled())
    fireEvent.change(within(oats).getByLabelText('Observed portion amount'), { target: { value: '50' } })
    fireEvent.click(within(oats).getByRole('button', { name: 'Apply item corrections' }))
    await waitFor(() => expect(smartEntryApi.correctInteraction).toHaveBeenCalledWith(
      'mixed-task', 2, expect.any(String), 'oats', 1, { amount: 50 }))
    await expect(vi.mocked(smartEntryApi.correctInteraction).mock.results[0].value).resolves.toMatchObject({
      version: 3, payload: { candidates: [expect.anything(), expect.objectContaining({ values: expect.objectContaining({ reps: 12 }) })] },
    })
    await screen.findByRole('alert')
    expect(screen.getByLabelText('Repetitions per set')).toHaveValue(8)
    expect(screen.getByRole('button', { name: 'Confirm training entries' })).toBeDisabled()
    expect(smartEntryApi.updateDraft).not.toHaveBeenCalled()
    expect(smartEntryApi.confirmDraft).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Load latest training' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Repetitions per set')).toHaveValue(12)
    expect(screen.getByRole('button', { name: 'Confirm training entries' })).toBeEnabled()
  })

  it('accepts its own saved canonical training and removes the editor after successful confirmation', async () => {
    const canonical = fixture()
    canonical.version = 3
    canonical.payload.candidates[1].values.reps = 8
    canonical.payload.candidates[1].values.exercise_type = 'strength'
    canonical.payload.candidates[1].issues = []
    canonical.payload.candidates[1].provenance = { source: 'public', catalog_id: 'squat-catalog' }
    vi.mocked(smartEntryApi.updateDraft).mockResolvedValue(canonical)
    vi.mocked(smartEntryApi.confirmDraft).mockRejectedValueOnce(new Error('response lost'))
      .mockResolvedValue({ draft_id: canonical.id, log_date: canonical.payload.log_date, meal_ids: [], training_session_id: 'session', replayed: true })
    const remaining = fixture()
    remaining.version = 4
    remaining.payload.candidates = [remaining.payload.candidates[0]]
    vi.mocked(smartEntryApi.getDraft).mockResolvedValue(remaining)
    render(page())
    await editReps()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm training entries' }))
    await screen.findByText('response lost')
    expect(screen.getByLabelText('Repetitions per set')).toHaveValue(8)
    expect(screen.getByRole('button', { name: 'Confirm training entries' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm training entries' }))
    await waitFor(() => expect(screen.queryByLabelText('Repetitions per set')).not.toBeInTheDocument())
    expect(smartEntryApi.updateDraft).toHaveBeenCalledOnce()
    expect(smartEntryApi.confirmDraft).toHaveBeenCalledTimes(2)
    expect(vi.mocked(smartEntryApi.confirmDraft).mock.calls[1]).toEqual(vi.mocked(smartEntryApi.confirmDraft).mock.calls[0])
  })

  it('revalidates merged training when the server changed a different field', async () => {
    const next = fixture()
    next.version = 3
    next.payload.candidates[1].values.load_kg = 70
    vi.mocked(smartEntryApi.correctInteraction).mockResolvedValue(next)
    render(page())
    await editReps()
    const oats = screen.getByRole('article', { name: 'Oats' })
    await waitFor(() => expect(within(oats).getByLabelText('Observed portion amount')).toBeEnabled())
    fireEvent.change(within(oats).getByLabelText('Observed portion amount'), { target: { value: '50' } })
    fireEvent.click(within(oats).getByRole('button', { name: 'Apply item corrections' }))
    await waitFor(() => expect(smartEntryApi.correctInteraction).toHaveBeenCalledOnce())
    await waitFor(() => expect(screen.getByLabelText('Load (kg)')).toHaveValue(70))
    expect(screen.getByLabelText('Repetitions per set')).toHaveValue(8)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm training entries' })).toBeEnabled()
    expect(smartEntryApi.updateDraft).not.toHaveBeenCalled()
    expect(smartEntryApi.confirmDraft).not.toHaveBeenCalled()
  })

  it('adopts catalog fields from its own training save before retrying a lost confirmation', async () => {
    const canonical = fixture()
    canonical.version = 3
    canonical.payload.candidates[1].values.reps = 8
    canonical.payload.candidates[1].issues = []
    vi.mocked(smartEntryApi.updateDraft).mockResolvedValue(canonical)
    vi.mocked(smartEntryApi.confirmDraft).mockRejectedValueOnce(new Error('response lost'))
      .mockResolvedValue({ draft_id: canonical.id, log_date: canonical.payload.log_date, meal_ids: [], training_session_id: 'session', replayed: true })
    const remaining = fixture()
    remaining.version = 4
    remaining.payload.candidates = [remaining.payload.candidates[0]]
    vi.mocked(smartEntryApi.getDraft).mockResolvedValue(remaining)
    render(page())
    await editReps()
    fireEvent.change(screen.getByLabelText('Primary muscle'), { target: { value: 'back' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm training entries' }))
    await screen.findByText('response lost')
    expect(vi.mocked(smartEntryApi.updateDraft).mock.calls[0][2].candidates[1].values.primary_muscle).toBe('back')
    expect(screen.getByLabelText('Primary muscle')).toHaveValue('legs')
    expect(screen.getByRole('button', { name: 'Confirm training entries' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm training entries' }))
    await waitFor(() => expect(screen.queryByLabelText('Repetitions per set')).not.toBeInTheDocument())
    expect(smartEntryApi.updateDraft).toHaveBeenCalledOnce()
    expect(smartEntryApi.confirmDraft).toHaveBeenCalledTimes(2)
    expect(vi.mocked(smartEntryApi.confirmDraft).mock.calls[1]).toEqual(vi.mocked(smartEntryApi.confirmDraft).mock.calls[0])
  })

  it('does not transfer local training edits to a new owner', async () => {
    const view = render(page())
    await editReps()
    auth.owner = 'user-2'
    vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue(fixture('user-2'))
    view.rerender(page())
    await waitFor(() => expect(screen.getByLabelText('Repetitions per set')).toHaveValue(null))
    expect(smartEntryApi.updateDraft).not.toHaveBeenCalled()
  })
})
