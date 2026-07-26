import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import { ApiRequestError } from '../services/api'
import { workoutApi } from '../services/workoutApi'
import type {
  ConfirmedWorkout,
  ExerciseCatalogItem,
  WorkoutDraft,
  WorkoutDraftCreate,
} from '../types/workouts'
import { WorkoutEntry } from './WorkoutEntry'

vi.mock('../services/workoutApi', () => ({
  workoutApi: {
    searchExercises: vi.fn(),
    setFavorite: vi.fn(),
    createCustomExercise: vi.fn(),
    createDraft: vi.fn(),
    findLatestDraft: vi.fn(),
    getDraft: vi.fn(),
    updateDraft: vi.fn(),
    deleteDraft: vi.fn(),
    confirmDraft: vi.fn(),
  },
}))

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ user: { user_id: 'user-1' } }),
}))

const squat: ExerciseCatalogItem = {
  id: 'exercise-squat',
  owner_user_id: null,
  source: 'public',
  source_name: 'free-exercise-db',
  source_record_id: 'barbell-squat',
  dataset_version: '2026-07-25',
  name: 'Barbell squat',
  exercise_type: 'strength',
  primary_muscle: 'quadriceps',
  secondary_muscles: ['glutes'],
  met: null,
  license: 'Unlicense',
  attribution: 'free-exercise-db',
  provenance: {},
  content_hash: 'hash',
  active: true,
  aliases: ['squat'],
  is_favorite: false,
  use_count: 0,
  last_used_at: null,
  rank_group: 3,
}

const running: ExerciseCatalogItem = {
  ...squat,
  id: 'exercise-running',
  source_name: 'Adult Compendium',
  source_record_id: 'running',
  name: 'Running',
  exercise_type: 'cardio',
  primary_muscle: 'cardiovascular',
  secondary_muscles: [],
  met: 8,
  license: null,
  attribution: '2024 Adult Compendium',
}

function draftFrom(input: WorkoutDraftCreate, version = 1): WorkoutDraft {
  return {
    id: 'draft-1',
    user_id: 'user-1',
    payload: {
      ...input,
      weight_kg_snapshot: 72,
      estimated_calories: input.duration_min ? 500 : null,
      estimate: input.duration_min
        ? { contains_estimates: true, strength: { calories: 210 } }
        : {},
      strength_exercises: input.strength_exercises.map((exercise) => ({
        catalog_exercise_id: exercise.catalog_exercise_id ?? null,
        exercise_name: 'Barbell squat',
        primary_muscle: 'quadriceps',
        secondary_muscles: ['glutes'],
        sets: exercise.sets,
        provenance: {},
        custom_exercise: exercise.custom_exercise ?? null,
      })),
      cardio_items: input.cardio_items.map((item) => ({
        catalog_exercise_id: item.catalog_exercise_id ?? null,
        activity_name: 'Running',
        primary_muscle: 'cardiovascular',
        secondary_muscles: [],
        duration_min: item.duration_min,
        device_calories: item.device_calories,
        met: 8,
        estimated_calories: item.device_calories ?? 403,
        is_estimate: item.device_calories === null,
        estimate: { method: item.device_calories === null ? 'met' : 'device' },
        provenance: {},
        custom_exercise: item.custom_exercise ?? null,
      })),
    },
    version,
    expires_at: '2026-08-24T00:00:00Z',
    created_at: '2026-07-25T00:00:00Z',
    updated_at: '2026-07-25T00:00:00Z',
  }
}

function confirmedFrom(draft: WorkoutDraft): ConfirmedWorkout {
  return {
    id: 'workout-1',
    user_id: draft.user_id,
    ...draft.payload,
    created_at: draft.created_at,
    updated_at: draft.updated_at,
    replayed: false,
  }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/today/workout/new?date=2026-07-25']}>
      <Routes>
        <Route path="/today/workout/new" element={<WorkoutEntry />} />
        <Route path="/" element={<h1>Today destination</h1>} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(async () => {
  vi.clearAllMocks()
  globalThis.localStorage.clear()
  await i18n.changeLanguage('en-US')
  vi.mocked(workoutApi.searchExercises).mockResolvedValue([squat, running])
  vi.mocked(workoutApi.findLatestDraft).mockResolvedValue(null)
  vi.mocked(workoutApi.createDraft).mockImplementation(async (input) => draftFrom(input))
  vi.mocked(workoutApi.updateDraft).mockImplementation(
    async (_id, version, input) => draftFrom(input, version + 1),
  )
  vi.mocked(workoutApi.confirmDraft).mockImplementation(async () => {
    const calls = vi.mocked(workoutApi.createDraft).mock.calls
    return confirmedFrom(draftFrom(calls[calls.length - 1][0]))
  })
})

describe('WorkoutEntry', () => {
  it('builds and confirms a compact strength session with initially empty numbers', async () => {
    renderPage()

    fireEvent.change(screen.getByLabelText('Search exercises'), {
      target: { value: 'squat' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByText('Barbell squat')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'Add exercise' })[0])

    expect(screen.getByLabelText('Sets for Barbell squat')).toHaveValue(null)
    expect(screen.getByLabelText('Reps for Barbell squat')).toHaveValue(null)
    expect(screen.getByLabelText('Load for Barbell squat')).toHaveValue(null)
    fireEvent.change(screen.getByLabelText('Session title'), {
      target: { value: 'Lower body' },
    })
    fireEvent.change(screen.getByLabelText('Sets for Barbell squat'), {
      target: { value: '3' },
    })
    fireEvent.change(screen.getByLabelText('Reps for Barbell squat'), {
      target: { value: '8' },
    })
    fireEvent.change(screen.getByLabelText('Load for Barbell squat'), {
      target: { value: '60' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Confirm workout' }))

    await waitFor(() => expect(workoutApi.createDraft).toHaveBeenCalledWith(
      expect.objectContaining({
        log_date: '2026-07-25',
        title: 'Lower body',
        strength_exercises: [{
          catalog_exercise_id: 'exercise-squat',
          sets: [
            { set_number: 1, reps: 8, load_kg: 60, bodyweight: false },
            { set_number: 2, reps: 8, load_kg: 60, bodyweight: false },
            { set_number: 3, reps: 8, load_kg: 60, bodyweight: false },
          ],
        }],
      }),
    ))
    expect(await screen.findByRole('heading', { name: 'Today destination' })).toBeInTheDocument()
  })

  it('saves cardio device calories and labels the measured result', async () => {
    renderPage()

    fireEvent.change(screen.getByLabelText('Search exercises'), {
      target: { value: 'running' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    await screen.findByText('Running')
    fireEvent.click(screen.getAllByRole('button', { name: 'Add exercise' })[1])

    expect(screen.getByLabelText('Duration for Running')).toHaveValue(null)
    expect(screen.getByLabelText('Device calories for Running')).toHaveValue(null)
    fireEvent.change(screen.getByLabelText('Duration for Running'), {
      target: { value: '30' },
    })
    fireEvent.change(screen.getByLabelText('Device calories for Running'), {
      target: { value: '280' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save draft' }))

    await waitFor(() => expect(workoutApi.createDraft).toHaveBeenCalledWith(
      expect.objectContaining({
        cardio_items: [{
          catalog_exercise_id: 'exercise-running',
          duration_min: 30,
          device_calories: 280,
        }],
      }),
    ))
    expect(await screen.findByText('Device value: 280 kcal')).toBeInTheDocument()
  })

  it('requires complete custom exercise identity before creating and adding it', async () => {
    vi.mocked(workoutApi.searchExercises).mockResolvedValue([])
    vi.mocked(workoutApi.createCustomExercise).mockImplementation(async (input) => ({
      ...squat,
      id: 'custom-deadlift',
      owner_user_id: 'user-1',
      source: 'user_custom',
      source_name: 'user',
      source_record_id: 'custom-deadlift',
      name: input.name,
      exercise_type: input.exercise_type,
      primary_muscle: input.primary_muscle,
      secondary_muscles: input.secondary_muscles,
      met: input.met,
      aliases: input.aliases,
    }))
    renderPage()

    fireEvent.change(screen.getByLabelText('Search exercises'), {
      target: { value: 'Trap bar deadlift' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByRole('heading', { name: 'Create custom exercise' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Create and add' }))
    expect(screen.getByText(/Enter a name and primary muscle/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Exercise name'), {
      target: { value: 'Trap bar deadlift' },
    })
    fireEvent.change(screen.getByLabelText('Primary muscle'), {
      target: { value: 'hamstrings' },
    })
    fireEvent.change(screen.getByLabelText('MET value'), {
      target: { value: '5.5' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create and add' }))

    await waitFor(() => expect(workoutApi.createCustomExercise).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'Trap bar deadlift',
        exercise_type: 'strength',
        primary_muscle: 'hamstrings',
        met: 5.5,
      }),
    ))
    expect(screen.getByLabelText('Sets for Trap bar deadlift')).toHaveValue(null)
  })

  it('expands compact strength sets for per-set reps and load', async () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    await screen.findByText('Barbell squat')
    fireEvent.click(screen.getAllByRole('button', { name: 'Add exercise' })[0])
    fireEvent.change(screen.getByLabelText('Sets for Barbell squat'), {
      target: { value: '2' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Edit each set' }))
    fireEvent.change(screen.getByLabelText('Reps for set 1 of Barbell squat'), {
      target: { value: '8' },
    })
    fireEvent.change(screen.getByLabelText('Reps for set 2 of Barbell squat'), {
      target: { value: '6' },
    })
    fireEvent.change(screen.getByLabelText('Load for set 1 of Barbell squat'), {
      target: { value: '60' },
    })
    fireEvent.change(screen.getByLabelText('Load for set 2 of Barbell squat'), {
      target: { value: '65' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save draft' }))

    await waitFor(() => expect(workoutApi.createDraft).toHaveBeenCalledWith(
      expect.objectContaining({
        strength_exercises: [expect.objectContaining({
          sets: [
            { set_number: 1, reps: 8, load_kg: 60, bodyweight: false },
            { set_number: 2, reps: 6, load_kg: 65, bodyweight: false },
          ],
        })],
      }),
    ))
  })

  it('labels only the strength component of a mixed-session estimate', async () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    await screen.findByText('Barbell squat')
    fireEvent.click(screen.getAllByRole('button', { name: 'Add exercise' })[0])
    fireEvent.change(screen.getByLabelText('Sets for Barbell squat'), {
      target: { value: '1' },
    })
    fireEvent.change(screen.getByLabelText('Reps for Barbell squat'), {
      target: { value: '8' },
    })
    const duration = screen.getAllByRole('spinbutton').find((input) => (
      input.getAttribute('step') === '0.1'
      && input.closest('.workout-session-fields') !== null
    ))
    if (!duration) throw new Error('session duration input missing')
    fireEvent.change(duration, { target: { value: '45' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Intensity' }), {
      target: { value: 'medium' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save draft' }))

    expect(await screen.findByText(/Estimated strength energy: 210 kcal/)).toBeInTheDocument()
    expect(screen.queryByText(/Estimated strength energy: 500 kcal/)).not.toBeInTheDocument()
  })

  it('preserves workout values and offers an explicit retry after a stale save', async () => {
    vi.mocked(workoutApi.updateDraft).mockRejectedValue(
      new ApiRequestError(
        'Workout draft changed in another session.',
        'WORKOUT_DRAFT_VERSION_CONFLICT',
        'deterministic',
        409,
      ),
    )
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    await screen.findByText('Barbell squat')
    fireEvent.click(screen.getAllByRole('button', { name: 'Add exercise' })[0])
    fireEvent.change(screen.getByLabelText('Sets for Barbell squat'), {
      target: { value: '3' },
    })
    fireEvent.change(screen.getByLabelText('Reps for Barbell squat'), {
      target: { value: '8' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save draft' }))
    await waitFor(() => expect(workoutApi.createDraft).toHaveBeenCalledOnce())
    fireEvent.change(screen.getByLabelText('Reps for Barbell squat'), {
      target: { value: '10' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm workout' }))

    expect(await screen.findByText('Workout draft changed in another session.')).toBeInTheDocument()
    expect(screen.getByLabelText('Reps for Barbell squat')).toHaveValue(10)
    expect(screen.getByRole('button', { name: 'Retry with my changes' })).toBeInTheDocument()
  })

  it('restores local form values and reconnects to the server draft', async () => {
    const input: WorkoutDraftCreate = {
      log_date: '2026-07-25',
      title: 'Recovered lower body',
      started_at: null,
      duration_min: null,
      intensity: null,
      entry_method: 'form',
      strength_exercises: [{
        catalog_exercise_id: squat.id,
        sets: [{ set_number: 1, reps: 10, load_kg: 50, bodyweight: false }],
      }],
      cardio_items: [],
    }
    globalThis.localStorage.setItem(
      'fitlife:workout-draft:user-1:2026-07-25',
      JSON.stringify({
        session: {
          logDate: '2026-07-25', title: 'Recovered lower body',
          startedAt: '', duration: '', intensity: '',
        },
        strength: [{
          key: `strength:${squat.id}`, exercise: squat, setCount: '1',
          reps: '10', load: '50', bodyweight: false, expanded: false,
          setRows: [],
        }],
        cardio: [],
        draftId: 'draft-1',
      }),
    )
    vi.mocked(workoutApi.getDraft).mockResolvedValue(draftFrom(input))

    renderPage()

    expect(screen.getByLabelText('Session title')).toHaveValue('Recovered lower body')
    expect(screen.getByLabelText('Reps for Barbell squat')).toHaveValue(10)
    await waitFor(() => expect(workoutApi.getDraft).toHaveBeenCalledWith('draft-1'))
  })

  it('does not restore another account local editor state', async () => {
    globalThis.localStorage.setItem(
      'fitlife:workout-draft:user-2:2026-07-25',
      JSON.stringify({
        session: {
          logDate: '2026-07-25', title: 'Private other session',
          startedAt: '', duration: '', intensity: '',
        },
        strength: [],
        cardio: [],
        draftId: null,
        pendingConfirmation: null,
      }),
    )

    renderPage()

    expect(screen.getByLabelText('Session title')).not.toHaveValue(
      'Private other session',
    )
    await waitFor(() => expect(workoutApi.findLatestDraft).toHaveBeenCalledWith(
      '2026-07-25',
    ))
  })

  it('moves local recovery state when the editable workout date changes', async () => {
    renderPage()
    fireEvent.change(screen.getByLabelText('Session title'), {
      target: { value: 'Date migration' },
    })
    await waitFor(() => expect(globalThis.localStorage.getItem(
      'fitlife:workout-draft:user-1:2026-07-25',
    )).not.toBeNull())

    fireEvent.change(screen.getByLabelText('Date'), {
      target: { value: '2026-07-26' },
    })

    await waitFor(() => {
      expect(globalThis.localStorage.getItem(
        'fitlife:workout-draft:user-1:2026-07-25',
      )).toBeNull()
      expect(globalThis.localStorage.getItem(
        'fitlife:workout-draft:user-1:2026-07-26',
      )).toContain('Date migration')
    })
  })

  it('restores an incomplete editor from the latest server draft', async () => {
    const editorState = {
      session: {
        logDate: '2026-07-25', title: 'Server partial session',
        startedAt: '', duration: '', intensity: '',
      },
      strength: [{
        key: `strength:${squat.id}`, exercise: squat, setCount: '',
        reps: '', load: '', bodyweight: false, expanded: false, setRows: [],
      }],
      cardio: [],
      draftId: null,
      pendingConfirmation: null,
    }
    const serverDraft = draftFrom({
      log_date: '2026-07-25',
      title: 'Server partial session',
      started_at: null,
      duration_min: null,
      intensity: null,
      entry_method: 'form',
      strength_exercises: [],
      cardio_items: [],
      recovery_state: editorState,
    })
    vi.mocked(workoutApi.findLatestDraft).mockResolvedValue(serverDraft)
    vi.mocked(workoutApi.getDraft).mockResolvedValue(serverDraft)

    renderPage()

    expect(await screen.findByDisplayValue('Server partial session')).toBeInTheDocument()
    expect(screen.getByLabelText('Sets for Barbell squat')).toHaveValue(null)
    expect(workoutApi.getDraft).toHaveBeenCalledWith('draft-1')
  })

  it('replays an in-flight confirmation after a page refresh', async () => {
    const functionalInput: WorkoutDraftCreate = {
      log_date: '2026-07-25',
      title: 'Refresh-safe session',
      started_at: null,
      duration_min: null,
      intensity: null,
      entry_method: 'form',
      strength_exercises: [{
        catalog_exercise_id: squat.id,
        sets: [{ set_number: 1, reps: 8, load_kg: 60, bodyweight: false }],
      }],
      cardio_items: [],
    }
    const key = '6ba7b810-9dad-11d1-80b4-00c04fd430c8'
    globalThis.localStorage.setItem(
      'fitlife:workout-draft:user-1:2026-07-25',
      JSON.stringify({
        session: {
          logDate: '2026-07-25', title: 'Refresh-safe session',
          startedAt: '', duration: '', intensity: '',
        },
        strength: [{
          key: `strength:${squat.id}`, exercise: squat, setCount: '1',
          reps: '8', load: '60', bodyweight: false, expanded: false,
          setRows: [],
        }],
        cardio: [],
        draftId: 'draft-1',
        pendingConfirmation: {
          draftId: 'draft-1',
          version: 1,
          idempotencyKey: key,
          fingerprint: JSON.stringify(functionalInput),
        },
      }),
    )
    vi.mocked(workoutApi.confirmDraft).mockResolvedValue(
      confirmedFrom(draftFrom(functionalInput)),
    )

    renderPage()

    expect(await screen.findByRole('heading', { name: 'Today destination' }))
      .toBeInTheDocument()
    expect(workoutApi.createDraft).not.toHaveBeenCalled()
    expect(workoutApi.updateDraft).not.toHaveBeenCalled()
    expect(workoutApi.confirmDraft).toHaveBeenCalledWith('draft-1', 1, key)
  })

  it('automatically saves a complete draft after editing settles', async () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    await screen.findByText('Barbell squat')
    fireEvent.click(screen.getAllByRole('button', { name: 'Add exercise' })[0])
    fireEvent.change(screen.getByLabelText('Sets for Barbell squat'), {
      target: { value: '2' },
    })
    fireEvent.change(screen.getByLabelText('Reps for Barbell squat'), {
      target: { value: '8' },
    })

    await waitFor(
      () => expect(workoutApi.createDraft).toHaveBeenCalledTimes(1),
      { timeout: 2500 },
    )
  })

  it('automatically saves incomplete fields in bounded server recovery state', async () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    await screen.findByText('Barbell squat')
    fireEvent.click(screen.getAllByRole('button', { name: 'Add exercise' })[0])

    await waitFor(
      () => expect(workoutApi.createDraft).toHaveBeenCalledWith(
        expect.objectContaining({
          strength_exercises: [],
          recovery_state: expect.objectContaining({
            strength: [expect.objectContaining({
              exercise: expect.objectContaining({ id: squat.id }),
              reps: '',
            })],
          }),
        }),
      ),
      { timeout: 2500 },
    )
  })

  it('requires MET or device calories for cardio before saving', async () => {
    const cardioWithoutMet = { ...running, id: 'cardio-no-met', met: null }
    vi.mocked(workoutApi.searchExercises).mockResolvedValue([cardioWithoutMet])
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    await screen.findByText('Running')
    fireEvent.click(screen.getByRole('button', { name: 'Add exercise' }))
    fireEvent.change(screen.getByLabelText('Duration for Running'), {
      target: { value: '30' },
    })

    expect(screen.getByText(/has no MET value/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save draft' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Device calories for Running'), {
      target: { value: '250' },
    })
    expect(screen.getByRole('button', { name: 'Save draft' })).toBeEnabled()
  })
})
