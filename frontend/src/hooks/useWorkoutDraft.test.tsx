import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiRequestError } from '../services/api'
import { workoutApi } from '../services/workoutApi'
import type { WorkoutDraft, WorkoutDraftCreate } from '../types/workouts'
import { useWorkoutDraft } from './useWorkoutDraft'

vi.mock('../services/workoutApi', () => ({
  workoutApi: {
    createDraft: vi.fn(),
    getDraft: vi.fn(),
    updateDraft: vi.fn(),
    confirmDraft: vi.fn(),
    deleteDraft: vi.fn(),
  },
}))

const initial: WorkoutDraftCreate = {
  log_date: '2026-07-25',
  title: 'Lower body',
  started_at: null,
  duration_min: 50,
  intensity: 'medium',
  entry_method: 'form',
  strength_exercises: [{
    catalog_exercise_id: 'exercise-squat',
    sets: [{ set_number: 1, reps: 8, load_kg: 60, bodyweight: false }],
  }],
  cardio_items: [],
}

const remoteDraft: WorkoutDraft = {
  id: 'draft-1',
  user_id: 'user-1',
  payload: {
    ...initial,
    weight_kg_snapshot: 72,
    estimated_calories: 210,
    estimate: { is_estimate: true },
    strength_exercises: [{
      catalog_exercise_id: 'exercise-squat',
      exercise_name: 'Squat',
      primary_muscle: 'quadriceps',
      secondary_muscles: ['glutes'],
      sets: initial.strength_exercises[0].sets,
      provenance: {},
      custom_exercise: null,
    }],
    cardio_items: [],
  },
  version: 1,
  expires_at: '2026-08-24T00:00:00Z',
  created_at: '2026-07-25T00:00:00Z',
  updated_at: '2026-07-25T00:00:00Z',
}

beforeEach(() => vi.clearAllMocks())

describe('useWorkoutDraft', () => {
  it('keeps local workout values and exposes WORKOUT conflict recovery', async () => {
    vi.mocked(workoutApi.createDraft).mockResolvedValue(remoteDraft)
    vi.mocked(workoutApi.updateDraft).mockRejectedValue(
      new ApiRequestError(
        'Workout draft changed in another session.',
        'WORKOUT_DRAFT_VERSION_CONFLICT',
        'deterministic',
        409,
      ),
    )
    const { result } = renderHook(() => useWorkoutDraft(initial))

    await act(async () => {
      await result.current.save()
    })
    const changed = { ...initial, title: 'Heavy lower body' }
    act(() => result.current.setInput(changed))
    let rejectedMessage = ''
    await act(async () => {
      try {
        await result.current.save()
      } catch (cause) {
        rejectedMessage = (cause as Error).message
      }
    })

    expect(rejectedMessage).toBe('Workout draft changed in another session.')
    await waitFor(() => expect(result.current.status).toBe('conflict'))
    expect(result.current.input).toEqual(changed)
    expect(result.current.draft?.version).toBe(1)
  })

  it('reuses one UUID confirmation key after a recoverable failure', async () => {
    vi.mocked(workoutApi.createDraft).mockResolvedValue(remoteDraft)
    vi.mocked(workoutApi.confirmDraft)
      .mockRejectedValueOnce(new Error('network unavailable'))
      .mockResolvedValueOnce({
        id: 'workout-1',
        user_id: 'user-1',
        ...remoteDraft.payload,
        created_at: remoteDraft.created_at,
        updated_at: remoteDraft.updated_at,
        replayed: false,
      })
    const uuid = vi.spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValue('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
    const { result } = renderHook(() => useWorkoutDraft(initial))

    await act(async () => {
      await result.current.save()
    })
    await expect(act(async () => result.current.confirm())).rejects.toThrow(
      'network unavailable',
    )
    await act(async () => {
      await result.current.confirm()
    })

    expect(uuid).toHaveBeenCalledTimes(1)
    expect(vi.mocked(workoutApi.confirmDraft).mock.calls[0][2]).toBe(
      vi.mocked(workoutApi.confirmDraft).mock.calls[1][2],
    )
  })

  it('replays confirmation without saving a deleted draft first', async () => {
    vi.mocked(workoutApi.createDraft).mockResolvedValue(remoteDraft)
    vi.mocked(workoutApi.confirmDraft)
      .mockRejectedValueOnce(new Error('response lost'))
      .mockResolvedValueOnce({
        id: 'workout-1',
        user_id: 'user-1',
        ...remoteDraft.payload,
        created_at: remoteDraft.created_at,
        updated_at: remoteDraft.updated_at,
        replayed: true,
      })
    const { result } = renderHook(() => useWorkoutDraft(initial))

    await expect(act(async () => result.current.saveAndConfirm(initial)))
      .rejects.toThrow('response lost')
    await act(async () => {
      await result.current.saveAndConfirm(initial)
    })

    expect(workoutApi.createDraft).toHaveBeenCalledTimes(1)
    expect(workoutApi.updateDraft).not.toHaveBeenCalled()
    expect(workoutApi.confirmDraft).toHaveBeenCalledTimes(2)
    expect(vi.mocked(workoutApi.confirmDraft).mock.calls[0][2]).toBe(
      vi.mocked(workoutApi.confirmDraft).mock.calls[1][2],
    )
  })

  it('replays a restored confirmation when only recovery metadata changed', async () => {
    vi.mocked(workoutApi.confirmDraft).mockResolvedValue({
      id: 'workout-1',
      user_id: 'user-1',
      ...remoteDraft.payload,
      created_at: remoteDraft.created_at,
      updated_at: remoteDraft.updated_at,
      replayed: true,
    })
    const pending = {
      draftId: 'draft-1',
      version: 1,
      idempotencyKey: '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
      fingerprint: JSON.stringify(initial),
    }
    const recoveredInput = {
      ...initial,
      recovery_state: {
        draftId: 'draft-1',
        pendingConfirmation: pending,
      },
    }
    const { result } = renderHook(() => useWorkoutDraft(recoveredInput))

    act(() => result.current.restorePendingConfirmation(pending))
    await act(async () => {
      await result.current.saveAndConfirm(recoveredInput)
    })

    expect(workoutApi.createDraft).not.toHaveBeenCalled()
    expect(workoutApi.updateDraft).not.toHaveBeenCalled()
    expect(workoutApi.confirmDraft).toHaveBeenCalledWith(
      'draft-1',
      1,
      pending.idempotencyKey,
    )
  })
})
