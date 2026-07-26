import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import { useSmartEntryDraft } from '../hooks/useSmartEntryDraft'
import type {
  SmartCandidate,
  SmartEntryDraft,
} from '../types/smartEntry'
import { SmartEntry } from './SmartEntry'


vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ user: { user_id: 'user-1' } }),
}))

vi.mock('../hooks/useSmartEntryDraft', () => ({
  useSmartEntryDraft: vi.fn(),
}))

const unresolvedFood: SmartCandidate = {
  id: 'candidate-food',
  kind: 'food',
  raw_text: 'homemade sandwich',
  normalized_text: 'homemade sandwich',
  subject_text: 'homemade sandwich',
  meal_context: 'lunch',
  selected: true,
  selected_catalog_id: null,
  catalog_choices: [],
  issues: ['SMART_ENTRY_CATALOG_UNMATCHED'],
  values: {
    name: 'homemade sandwich',
    amount: null,
    unit: '',
    calories: null,
    carbs: null,
    protein: null,
    fat: null,
  },
  provenance: { source: 'unresolved' },
  assumptions: [],
  agent_estimate_accepted: false,
}

const estimatedFood: SmartCandidate = {
  ...unresolvedFood,
  issues: ['SMART_ENTRY_AGENT_ESTIMATE_ACCEPTANCE_REQUIRED'],
  values: {
    name: 'homemade sandwich',
    amount: 1,
    unit: 'serving',
    calories: 420,
    carbs: 38,
    protein: 24,
    fat: 19,
    source: 'agent_estimate',
    is_estimate: true,
  },
  provenance: { source: 'agent_estimate' },
  assumptions: ['One medium sandwich'],
}

const completeStrength: SmartCandidate = {
  id: 'candidate-strength',
  kind: 'strength',
  raw_text: 'squat 3x8 60kg',
  normalized_text: 'squat 3x8 60kg',
  subject_text: 'squat',
  meal_context: null,
  selected: true,
  selected_catalog_id: 'exercise-squat',
  catalog_choices: [],
  issues: [],
  values: {
    name: 'Barbell squat',
    primary_muscle: 'quadriceps',
    set_count: 3,
    reps: 8,
    load_kg: 60,
    source: 'public',
  },
  provenance: { source: 'public', source_name: 'free-exercise-db' },
  assumptions: [],
  agent_estimate_accepted: false,
}

function draftWith(candidates: SmartCandidate[]): SmartEntryDraft {
  return {
    id: 'draft-1',
    user_id: 'user-1',
    payload: {
      log_date: '2026-07-26',
      raw_text: candidates.map((candidate) => candidate.raw_text).join('\n'),
      parser_version: 'smart-entry-parser-v1',
      candidates,
    },
    version: 1,
    agent_status: 'not_requested',
    agent_prompt_version: null,
    agent_model: null,
    agent_metadata: {},
    expires_at: '2026-08-25T00:00:00Z',
    created_at: '2026-07-26T00:00:00Z',
    updated_at: '2026-07-26T00:00:00Z',
  }
}

function hookState(
  candidates: SmartCandidate[],
  overrides: Partial<ReturnType<typeof useSmartEntryDraft>> = {},
) {
  const draft = draftWith(candidates)
  return {
    draft,
    confirmed: null,
    status: 'idle' as const,
    error: null,
    restore: vi.fn().mockResolvedValue(null),
    parse: vi.fn().mockResolvedValue(draft),
    save: vi.fn().mockResolvedValue(draft),
    analyze: vi.fn().mockResolvedValue(draft),
    confirm: vi.fn().mockResolvedValue({
      draft_id: draft.id,
      log_date: draft.payload.log_date,
      meal_ids: [],
      training_session_id: 'training-1',
      replayed: false,
    }),
    discard: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/today/smart-entry?date=2026-07-26']}>
      <Routes>
        <Route path="/today/smart-entry" element={<SmartEntry />} />
        <Route path="/" element={<h1>Today destination</h1>} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(async () => {
  vi.clearAllMocks()
  globalThis.localStorage.clear()
  await i18n.changeLanguage('en-US')
})

describe('SmartEntry', () => {
  it('parses deterministically and calls Agent analysis only after a click', async () => {
    const state = hookState([unresolvedFood])
    vi.mocked(useSmartEntryDraft).mockReturnValue(state)
    renderPage()

    fireEvent.change(screen.getByLabelText('Meal and training notes'), {
      target: { value: 'homemade sandwich' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Parse entry' }))

    expect(await screen.findByDisplayValue('homemade sandwich')).toBeInTheDocument()
    expect(state.analyze).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Amount')).toHaveValue(null)
    expect(screen.getByLabelText('Calories (kcal)')).toHaveValue(null)

    fireEvent.click(screen.getByRole('button', {
      name: 'Analyze unresolved fields',
    }))
    await waitFor(() => expect(state.analyze).toHaveBeenCalledOnce())
  })

  it('preserves deterministic candidates and local edits after analysis fails', async () => {
    const state = hookState([unresolvedFood], {
      analyze: vi.fn().mockRejectedValue(new Error('model unavailable')),
    })
    vi.mocked(useSmartEntryDraft).mockReturnValue(state)
    renderPage()

    fireEvent.change(screen.getByLabelText('Meal and training notes'), {
      target: { value: 'homemade sandwich' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Parse entry' }))
    await screen.findByDisplayValue('homemade sandwich')
    fireEvent.change(screen.getByLabelText('Amount'), {
      target: { value: '1' },
    })
    fireEvent.change(screen.getByLabelText('Unit'), {
      target: { value: 'serving' },
    })
    fireEvent.click(screen.getByRole('button', {
      name: 'Analyze unresolved fields',
    }))

    await waitFor(() => expect(state.analyze).toHaveBeenCalledOnce())
    expect(screen.getByLabelText('Amount')).toHaveValue(1)
    expect(screen.getByLabelText('Unit')).toHaveValue('serving')
    expect(screen.getByLabelText('Food name')).toHaveValue(
      'homemade sandwich',
    )
  })

  it('requires explicit estimate acceptance before confirmation', async () => {
    const state = hookState([estimatedFood])
    vi.mocked(useSmartEntryDraft).mockReturnValue(state)
    renderPage()

    fireEvent.change(screen.getByLabelText('Meal and training notes'), {
      target: { value: 'homemade sandwich' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Parse entry' }))
    await screen.findByText('One medium sandwich')

    const confirm = screen.getByRole('button', {
      name: 'Confirm selected entries',
    })
    expect(confirm).toBeDisabled()
    fireEvent.click(screen.getByLabelText(
      'I reviewed and accept this AI estimate.',
    ))
    expect(confirm).toBeEnabled()
  })

  it('confirms complete selected candidates and returns to the selected day', async () => {
    const state = hookState([completeStrength])
    vi.mocked(useSmartEntryDraft).mockReturnValue(state)
    renderPage()

    fireEvent.change(screen.getByLabelText('Meal and training notes'), {
      target: { value: 'squat 3x8 60kg' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Parse entry' }))
    await screen.findByDisplayValue('Barbell squat')
    fireEvent.click(screen.getByRole('button', {
      name: 'Confirm selected entries',
    }))

    expect(await screen.findByRole('heading', { name: 'Today destination' }))
      .toBeInTheDocument()
    expect(state.confirm).toHaveBeenCalledWith(expect.objectContaining({
      log_date: '2026-07-26',
      candidates: [completeStrength],
    }))
  })
})
