import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { useSmartEntryDraft } from '../hooks/useSmartEntryDraft'
import { smartEntryApi } from '../services/smartEntryApi'
import { clearSmartEntryRecovery } from '../services/smartEntryRecovery'
import type { SmartCandidate, SmartEntryDraft } from '../types/smartEntry'
import { SmartEntry } from './SmartEntry'

vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ user: { user_id: 'user-1' } }) }))
vi.mock('../services/smartEntryApi', () => ({ smartEntryApi: {
  capabilities: vi.fn(), findLatestDraft: vi.fn(), getDraft: vi.fn(), createDraft: vi.fn(),
  updateDraft: vi.fn(), deleteDraft: vi.fn(), analyzeDraft: vi.fn(), confirmDraft: vi.fn(),
  startInteraction: vi.fn(), answerInteraction: vi.fn(), correctInteraction: vi.fn(), confirmItems: vi.fn(),
} }))
const key = 'fitlife:smart-entry:user-1:2026-07-26'
function fixture(): SmartEntryDraft {
  const food: SmartCandidate = {
    id: 'oats', kind: 'food', raw_text: 'Oats', normalized_text: 'Oats', subject_text: 'Oats',
    meal_context: 'breakfast', selected: true, selected_catalog_id: null,
    catalog_choices: [], issues: [], provenance: {}, assumptions: [], agent_estimate_accepted: false,
    values: { name: 'Oats', amount: 100, unit: 'g', intake_ratio: 0.5, calories: 100, carbs: 10, protein: 5, fat: 2, basis_type: 'per_100g' },
  }
  return {
    id: 'mixed-task', user_id: 'user-1', version: 2,
    payload: { log_date: '2026-07-26', raw_text: 'Oats and squat', parser_version: 'v1', candidates: [food,
      { ...food, id: 'squat', kind: 'strength', raw_text: 'Squat', normalized_text: 'Squat',
        subject_text: 'Squat', meal_context: null, selected_catalog_id: 'squat-catalog',
        issues: ['SMART_ENTRY_STRENGTH_VOLUME_REQUIRED'],
        values: { name: 'Squat', primary_muscle: 'legs', set_count: 3, reps: null, load_kg: 60 } }],
      interaction: { schema_version: 2, active: true, clarification_rounds: 1, status: 'awaiting_confirmation',
        items: [{ item_id: food.id, revision: 2, state: 'ready', values: food.values,
          sources: { calories: 'user_provided' }, assumptions: [], missing_fields: [] }], question_groups: [] } },
    agent_status: 'not_requested', agent_prompt_version: null, agent_model: null, agent_metadata: {},
    item_commits: [], dependency_validity: [], expires_at: '2027-01-01T00:00:00Z',
    created_at: '2026-07-26T00:00:00Z', updated_at: '2026-07-26T00:00:00Z',
  }
}
function completed() {
  const current = fixture()
  current.payload.candidates[1].values.reps = 8
  current.payload.candidates[1].issues = []
  return current
}
beforeEach(async () => {
  vi.restoreAllMocks()
  Object.values(smartEntryApi).forEach((method) => vi.mocked(method).mockReset())
  localStorage.clear()
  await i18n.changeLanguage('en-US')
  vi.mocked(smartEntryApi.capabilities).mockResolvedValue({ interactive_entry_enabled: false, entry_task_ttl_days: 30 })
  vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue(fixture())
  vi.mocked(smartEntryApi.updateDraft).mockImplementation(async (_id, _version, payload) => ({
    ...fixture(), version: 3, payload: { ...payload, interaction: fixture().payload.interaction },
  }))
  vi.mocked(smartEntryApi.confirmDraft).mockResolvedValue({ draft_id: 'mixed-task', log_date: '2026-07-26', meal_ids: [], training_session_id: 'training', replayed: false })
  vi.mocked(smartEntryApi.getDraft).mockResolvedValue({ ...completed(), version: 4 })
})

describe('active mixed training editor', () => {
  it('allows missing reps to be completed and saved before training confirmation while food is disabled', async () => {
    render(<MemoryRouter initialEntries={['/today/smart-entry?date=2026-07-26']}><SmartEntry /></MemoryRouter>)
    const reps = await screen.findByLabelText('Repetitions per set')
    expect(reps).toBeEnabled()
    expect(screen.getByLabelText('Record type Squat')).toBeDisabled()
    fireEvent.change(reps, { target: { value: '8' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm training entries' }))
    await waitFor(() => expect(smartEntryApi.confirmDraft).toHaveBeenCalledWith('mixed-task', 3, expect.any(String)))
    expect(smartEntryApi.updateDraft).toHaveBeenCalledOnce()
    const sent = vi.mocked(smartEntryApi.updateDraft).mock.calls[0][2]
    expect(sent.candidates[0]).toEqual(fixture().payload.candidates[0])
    expect(sent.candidates[1].values.reps).toBe(8)
    expect(smartEntryApi.analyzeDraft).not.toHaveBeenCalled()
  })

  it('saves changed training only once and retries the same confirmation after a lost response', async () => {
    vi.mocked(smartEntryApi.confirmDraft).mockRejectedValue(new Error('response lost'))
    const { result } = renderHook(() => useSmartEntryDraft(key))
    await act(async () => { await result.current.restore('2026-07-26') })
    const body = completed().payload
    await act(async () => { await result.current.confirm(body).catch(() => {}) })
    await act(async () => { await result.current.confirm(body).catch(() => {}) })
    expect(smartEntryApi.updateDraft).toHaveBeenCalledOnce()
    expect(smartEntryApi.confirmDraft).toHaveBeenCalledTimes(2)
    expect(vi.mocked(smartEntryApi.confirmDraft).mock.calls[1]).toEqual(vi.mocked(smartEntryApi.confirmDraft).mock.calls[0])
  })

  it('retries the canonical training returned by server normalization with the same key and no second PATCH', async () => {
    const canonical = completed()
    canonical.version = 3
    canonical.payload.candidates[1].values.exercise_type = 'strength'
    canonical.payload.candidates[1].provenance = { source: 'public', catalog_id: 'squat-catalog' }
    vi.mocked(smartEntryApi.updateDraft).mockResolvedValue(canonical)
    vi.mocked(smartEntryApi.confirmDraft).mockRejectedValue(new Error('response lost'))
    const { result } = renderHook(() => useSmartEntryDraft(key))
    await act(async () => { await result.current.restore('2026-07-26') })
    await act(async () => { await result.current.confirm(completed().payload).catch(() => {}) })
    expect(result.current.draft).toEqual(canonical)
    await act(async () => { await result.current.confirm(canonical.payload).catch(() => {}) })
    expect(smartEntryApi.updateDraft).toHaveBeenCalledOnce()
    expect(smartEntryApi.confirmDraft).toHaveBeenCalledTimes(2)
    expect(vi.mocked(smartEntryApi.confirmDraft).mock.calls[1]).toEqual(vi.mocked(smartEntryApi.confirmDraft).mock.calls[0])
  })

  it('rejects a changed canonical training body while its confirmation is pending', async () => {
    const canonical = completed()
    canonical.version = 3
    canonical.payload.candidates[1].values.exercise_type = 'strength'
    canonical.payload.candidates[1].provenance = { source: 'public', catalog_id: 'squat-catalog' }
    vi.mocked(smartEntryApi.updateDraft).mockResolvedValue(canonical)
    vi.mocked(smartEntryApi.confirmDraft).mockRejectedValue(new Error('response lost'))
    const { result } = renderHook(() => useSmartEntryDraft(key))
    await act(async () => { await result.current.restore('2026-07-26') })
    await act(async () => { await result.current.confirm(completed().payload).catch(() => {}) })
    const changed = structuredClone(canonical.payload)
    changed.candidates[1].values.reps = 9
    await act(async () => { await expect(result.current.confirm(changed)).rejects.toThrow('SMART_ENTRY_RECOVERY_REVIEW_REQUIRED') })
    expect(smartEntryApi.confirmDraft).toHaveBeenCalledOnce()
    expect(smartEntryApi.updateDraft).toHaveBeenCalledOnce()
  })

  it('requires review instead of replaying pending confirmation with a different training body', async () => {
    vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue(completed())
    vi.mocked(smartEntryApi.confirmDraft).mockRejectedValue(new Error('response lost'))
    const { result } = renderHook(() => useSmartEntryDraft(key))
    await act(async () => { await result.current.restore('2026-07-26') })
    await act(async () => { await result.current.confirm(completed().payload).catch(() => {}) })
    const changed = completed().payload
    changed.candidates[1].values.reps = 9
    await act(async () => { await expect(result.current.confirm(changed)).rejects.toThrow('SMART_ENTRY_RECOVERY_REVIEW_REQUIRED') })
    expect(smartEntryApi.confirmDraft).toHaveBeenCalledOnce()
    expect(smartEntryApi.updateDraft).not.toHaveBeenCalled()
  })

  it('keeps unchanged active confirmation free of PATCH', async () => {
    vi.mocked(smartEntryApi.findLatestDraft).mockResolvedValue(completed())
    const { result } = renderHook(() => useSmartEntryDraft(key))
    await act(async () => { await result.current.restore('2026-07-26') })
    await act(async () => { await result.current.confirm(completed().payload) })
    expect(smartEntryApi.updateDraft).not.toHaveBeenCalled()
    expect(smartEntryApi.confirmDraft).toHaveBeenCalledWith('mixed-task', 2, expect.any(String))
  })

  it('does not confirm training after logout between its PATCH and confirmation', async () => {
    vi.mocked(smartEntryApi.updateDraft).mockImplementation(async (_id, _version, payload) => {
      queueMicrotask(() => queueMicrotask(() => queueMicrotask(() => clearSmartEntryRecovery('user-1'))))
      return { ...fixture(), version: 3, payload: { ...payload, interaction: fixture().payload.interaction } }
    })
    const { result } = renderHook(() => useSmartEntryDraft(key))
    await act(async () => { await result.current.restore('2026-07-26') })
    await act(async () => { await result.current.confirm(completed().payload).catch(() => {}) })
    expect(smartEntryApi.updateDraft).toHaveBeenCalledOnce()
    expect(smartEntryApi.confirmDraft).not.toHaveBeenCalled()
    expect(result.current.draft).toBeNull()
    expect(localStorage.getItem(key)).toBeNull()
  })
})
