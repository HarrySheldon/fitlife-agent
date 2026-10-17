import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { smartEntryApi } from '../services/smartEntryApi'
import type { EntryItem, SmartCandidate, SmartEntryDraft } from '../types/smartEntry'
import { SmartEntry } from './SmartEntry'

vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ user: { user_id: 'user-1' } }) }))
vi.mock('../services/smartEntryApi', () => ({ smartEntryApi: {
  capabilities: vi.fn(), findLatestDraft: vi.fn(), getDraft: vi.fn(), createDraft: vi.fn(),
  updateDraft: vi.fn(), deleteDraft: vi.fn(), analyzeDraft: vi.fn(), confirmDraft: vi.fn(),
  startInteraction: vi.fn(), answerInteraction: vi.fn(), correctInteraction: vi.fn(), confirmItems: vi.fn(),
} }))
const food = (id: string, name: string): SmartCandidate => ({
  id, kind: 'food', raw_text: name, normalized_text: name, subject_text: name, meal_context: 'breakfast',
  selected: true, selected_catalog_id: null, catalog_choices: [], issues: [], values: { name }, provenance: {}, assumptions: [], agent_estimate_accepted: false,
})
const item = (id: string, name: string, ready = true): EntryItem => ({
  item_id: id, revision: 1, state: ready ? 'ready' : 'needs_clarification',
  values: { name, amount: ready ? 100 : null, unit: 'g', intake_ratio: 1, calories: ready ? 200 : null, carbs: 20, protein: 10, fat: 4, basis_type: 'per_100g' },
  sources: { name: 'user_provided', amount: 'user_provided', unit: 'user_provided', intake_ratio: 'user_provided', calories: 'user_provided', carbs: 'user_provided', protein: 'user_provided', fat: 'user_provided', basis_type: 'user_provided' },
  assumptions: [], missing_fields: ready ? [] : ['amount', 'calories'],
})
function fixture(): SmartEntryDraft {
  return {
    id: 'task-1', user_id: 'user-1', version: 2,
    payload: { log_date: '2026-07-26', raw_text: 'oats and banana', parser_version: 'v1', candidates: [food('oats', 'Oats'), food('banana', 'Banana')],
      interaction: { schema_version: 2, active: true, clarification_rounds: 0, status: 'awaiting_confirmation', items: [item('oats', 'Oats'), item('banana', 'Banana', false)], question_groups: [] } },
    agent_status: 'completed', agent_prompt_version: null, agent_model: null, agent_metadata: {}, item_commits: [], dependency_validity: [],
    expires_at: '2026-08-25T00:00:00Z', created_at: '2026-07-26T00:00:00Z', updated_at: '2026-07-26T02:00:00Z',
  }
}
function page() { return render(<MemoryRouter initialEntries={['/today/smart-entry?date=2026-07-26']}><SmartEntry /></MemoryRouter>) }
beforeEach(async () => {
  vi.restoreAllMocks()
  Object.values(smartEntryApi).forEach((method) => vi.mocked(method).mockReset())
  localStorage.clear()
  await i18n.changeLanguage('en-US')
  vi.mocked(smartEntryApi.capabilities).mockResolvedValue({ interactive_entry_enabled: true, entry_task_ttl_days: 30 })
  vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue(fixture())
})
describe('interactive smart entry with the real draft hook', () => {
  it('omits saved targets from the current question group and answers only editable missing fields', async () => {
    const current = fixture()
    current.payload.interaction!.items[0].state = 'saved'
    current.payload.interaction!.clarification_rounds = 1
    current.payload.interaction!.question_groups = [{ group_id: 'pending', expected_version: 2, asked_at: '2026-07-26T00:00:00Z', answered: false,
      questions: [{ item_id: 'oats', field: 'amount', portion_options: ['100'] }, { item_id: 'banana', field: 'amount', portion_options: ['100'] }] }]
    vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue(current)
    vi.mocked(smartEntryApi.answerInteraction).mockRejectedValue(new Error('response lost'))
    page()
    const panel = await screen.findByRole('region', { name: 'Food clarification' })
    expect(within(panel).getAllByRole('group')).toHaveLength(1)
    expect(within(panel).queryByText(/Oats/)).not.toBeInTheDocument()
    fireEvent.click(within(panel).getByLabelText('I don’t know'))
    fireEvent.click(within(panel).getByRole('button', { name: 'Submit answers' }))
    await waitFor(() => expect(smartEntryApi.answerInteraction).toHaveBeenCalledWith('task-1', 2, expect.any(String), 'pending', [{ item_id: 'banana', field: 'amount', value: null }]))
  })

  it('keeps manual corrections after failure and sends only changed fields for one item', async () => {
    vi.mocked(smartEntryApi.correctInteraction).mockRejectedValue(new Error('temporary failure'))
    page()
    const banana = await screen.findByRole('article', { name: 'Banana' })
    fireEvent.change(within(banana).getByLabelText('Observed portion amount'), { target: { value: '50' } })
    fireEvent.change(within(banana).getByLabelText('Intake ratio (0–1)'), { target: { value: '0.5' } })
    fireEvent.click(within(banana).getByRole('button', { name: 'Apply item corrections' }))
    await screen.findByText('temporary failure')
    expect(within(banana).getByLabelText('Observed portion amount')).toHaveValue(50)
    expect(within(banana).getByLabelText('Intake ratio (0–1)')).toHaveValue(0.5)
    expect(within(screen.getByRole('article', { name: 'Oats' })).getByLabelText('Observed portion amount')).toHaveValue(100)
    expect(smartEntryApi.correctInteraction).toHaveBeenCalledWith('task-1', 2, expect.any(String), 'banana', 1, { amount: 50, intake_ratio: 0.5 })
  })

  it('shows externally changed and deleted saved records honestly without offering recreation', async () => {
    const saved = fixture()
    saved.payload.interaction!.items.forEach((entry) => { entry.state = 'saved' })
    saved.item_commits = [
      { item_id: 'oats', item_revision: 1, meal_id: 'meal', meal_item_id: 'oats', record_state: 'changed' },
      { item_id: 'banana', item_revision: 1, meal_id: 'meal', meal_item_id: 'banana', record_state: 'deleted' },
    ]
    vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue(saved)
    page()
    expect(await screen.findByText('The formal record has been edited since this item was saved.')).toBeInTheDocument()
    expect(screen.getByText('The formal record was deleted. This task will not recreate it.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Select Oats to save')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Select Banana to save')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save selected food items' })).toBeDisabled()
    expect(smartEntryApi.confirmItems).not.toHaveBeenCalled()
  })

  it('restores using GET only, and saves just one selected item while another remains editable', async () => {
    const saved = fixture()
    saved.version = 3
    saved.payload.interaction!.items[0].state = 'saved'
    saved.item_commits = [{ item_id: 'oats', item_revision: 1, meal_id: 'meal-1', meal_item_id: 'meal-item-1', record_state: 'unchanged' }]
    vi.mocked(smartEntryApi.confirmItems).mockResolvedValue({ draft_id: 'task-1', commits: saved.item_commits, remaining_draft_version: 3, replayed: false })
    vi.mocked(smartEntryApi.getDraft).mockResolvedValue(saved)
    page()
    expect(await screen.findByText(/Recovered from the server/)).toBeInTheDocument()
    expect(smartEntryApi.startInteraction).not.toHaveBeenCalled()
    expect(smartEntryApi.confirmItems).not.toHaveBeenCalled()
    fireEvent.click(screen.getByLabelText('Select Oats to save'))
    fireEvent.click(screen.getByRole('button', { name: 'Save selected food items' }))
    await screen.findByText('Saved')
    expect(smartEntryApi.confirmItems).toHaveBeenCalledWith('task-1', 2, expect.any(String), [{ item_id: 'oats', item_revision: 1 }], [])
    expect(smartEntryApi.getDraft).toHaveBeenCalledWith('task-1')
    expect(within(screen.getByRole('article', { name: 'Oats' })).getByLabelText('Observed portion amount')).toBeDisabled()
    expect(within(screen.getByRole('article', { name: 'Banana' })).getByLabelText('Observed portion amount')).toBeEnabled()
    expect(screen.getByRole('link', { name: /Open Logbook/ })).toBeInTheDocument()
  })

  it('retains selection after a failed save and retries the identical command key', async () => {
    vi.mocked(smartEntryApi.confirmItems).mockRejectedValue(new Error('response lost'))
    page()
    fireEvent.click(await screen.findByLabelText('Select Oats to save'))
    const save = screen.getByRole('button', { name: 'Save selected food items' })
    fireEvent.click(save)
    await screen.findByRole('alert')
    expect(screen.queryByText('Saved')).not.toBeInTheDocument()
    fireEvent.click(save)
    await waitFor(() => expect(smartEntryApi.confirmItems).toHaveBeenCalledTimes(2))
    expect(vi.mocked(smartEntryApi.confirmItems).mock.calls[1]).toEqual(vi.mocked(smartEntryApi.confirmItems).mock.calls[0])
    const persisted = localStorage.getItem('fitlife:smart-entry:user-1:2026-07-26')!
    expect(persisted).not.toContain('Oats')
    expect(persisted).not.toContain('calories')
  })

  it('refreshes on 409 without replay, and invalidates estimate acceptance when revision changes', async () => {
    const initial = fixture()
    initial.payload.interaction!.items[0].sources.calories = 'estimated'
    vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue(initial)
    const latest = structuredClone(initial)
    latest.version = 3; latest.payload.interaction!.items[0].revision = 2
    vi.mocked(smartEntryApi.confirmItems).mockRejectedValue(Object.assign(new Error('version conflict'), { status: 409 }))
    vi.mocked(smartEntryApi.getDraft).mockResolvedValue(latest)
    page()
    fireEvent.click(await screen.findByLabelText('Select Oats to save'))
    const acceptance = screen.getByLabelText('I reviewed and accept this revision’s estimated values.')
    fireEvent.click(acceptance)
    fireEvent.click(screen.getByRole('button', { name: 'Save selected food items' }))
    await screen.findByText('version conflict')
    expect(smartEntryApi.getDraft).toHaveBeenCalledOnce()
    expect(smartEntryApi.confirmItems).toHaveBeenCalledOnce()
    expect(acceptance).not.toBeChecked()
    expect(screen.getByLabelText('Select Oats to save')).not.toBeChecked()
    expect(screen.getByRole('button', { name: 'Save selected food items' })).toBeDisabled()
    expect(screen.getByText('Estimated')).toBeInTheDocument()
  })

  it('answers unknown with null and offers manual correction after two rounds without another question request', async () => {
    const initial = fixture()
    initial.payload.interaction!.clarification_rounds = 2
    initial.payload.interaction!.question_groups = [
      { group_id: 'old', expected_version: 1, asked_at: '2026-07-26T00:00:00Z', answered: true, questions: [{ item_id: 'banana', field: 'unit', portion_options: ['g'] }] },
      { group_id: 'current', expected_version: 2, asked_at: '2026-07-26T01:00:00Z', answered: false, questions: [{ item_id: 'banana', field: 'amount', portion_options: ['100'] }] },
    ]
    vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue(initial)
    const answered = structuredClone(initial)
    answered.version = 3; answered.payload.interaction!.question_groups[1].answered = true
    vi.mocked(smartEntryApi.answerInteraction).mockResolvedValue(answered)
    page()
    const panel = await screen.findByRole('region', { name: 'Food clarification' })
    expect(within(panel).getAllByRole('group')).toHaveLength(1)
    fireEvent.click(within(panel).getByLabelText('I don’t know'))
    fireEvent.click(within(panel).getByRole('button', { name: 'Submit answers' }))
    await screen.findByText(/Two clarification rounds are complete/)
    expect(smartEntryApi.answerInteraction).toHaveBeenCalledWith('task-1', 2, expect.any(String), 'current', [{ item_id: 'banana', field: 'amount', value: null }])
    expect(smartEntryApi.startInteraction).not.toHaveBeenCalled()
    const banana = screen.getByRole('article', { name: 'Banana' })
    fireEvent.change(within(banana).getByLabelText('Consumed calories (kcal)'), { target: { value: '75' } })
    expect(within(banana).getByLabelText('Consumed calories (kcal)')).toHaveValue(75)
    expect(within(banana).getByText('Manual calories and macros are the total nutrition already consumed.')).toBeInTheDocument()
  })

  it('keeps active foods read-only when disabled and confirms existing training without PATCH', async () => {
    const initial = fixture()
    initial.payload.candidates.push({ ...food('squat', 'Squat'), kind: 'strength', meal_context: null, selected_catalog_id: 'squat', values: { name: 'Squat', primary_muscle: 'legs', set_count: 3, reps: 8 } })
    initial.payload.interaction!.status = 'completed'
    vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue(initial)
    vi.mocked(smartEntryApi.capabilities).mockResolvedValue({ interactive_entry_enabled: false, entry_task_ttl_days: 30 })
    vi.mocked(smartEntryApi.confirmDraft).mockResolvedValue({ draft_id: initial.id, log_date: initial.payload.log_date, meal_ids: [], training_session_id: 'training-1', replayed: false })
    vi.mocked(smartEntryApi.getDraft).mockResolvedValue(initial)
    page()
    const training = await screen.findByRole('button', { name: 'Confirm training entries' })
    expect(within(screen.getByRole('article', { name: 'Oats' })).getByLabelText('Food name')).toBeDisabled()
    fireEvent.click(training)
    await waitFor(() => expect(smartEntryApi.confirmDraft).toHaveBeenCalledWith('task-1', 2, expect.any(String)))
    await waitFor(() => expect(smartEntryApi.getDraft).toHaveBeenCalledWith('task-1'))
    expect(smartEntryApi.updateDraft).not.toHaveBeenCalled()
    expect(screen.getByRole('article', { name: 'Banana' })).toBeInTheDocument()
  })

  it('requires an explicit start action for an inactive task', async () => {
    const inactive = fixture(); inactive.payload.interaction!.active = false
    vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue(inactive)
    vi.mocked(smartEntryApi.startInteraction).mockResolvedValue(fixture())
    page()
    const start = await screen.findByRole('button', { name: 'Start food clarification' })
    expect(smartEntryApi.startInteraction).not.toHaveBeenCalled()
    fireEvent.click(start)
    await screen.findByLabelText('Select Oats to save')
    expect(smartEntryApi.startInteraction).toHaveBeenCalledWith('task-1', 2, expect.any(String))
  })
})
