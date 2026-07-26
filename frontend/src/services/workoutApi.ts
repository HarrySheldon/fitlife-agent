import type {
  ConfirmedWorkout,
  CustomExerciseInput,
  ExerciseCatalogItem,
  WorkoutDraft,
  WorkoutDraftCreate,
} from '../types/workouts'
import { requestV1 } from './api'

export const workoutApi = {
  searchExercises(query: string, limit = 20): Promise<ExerciseCatalogItem[]> {
    const params = new URLSearchParams({ q: query, limit: String(limit) })
    return requestV1(`/catalog/exercises/search?${params.toString()}`)
  },

  createCustomExercise(input: CustomExerciseInput): Promise<ExerciseCatalogItem> {
    return requestV1('/catalog/exercises/custom', {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },

  setFavorite(exerciseId: string, favorite: boolean): Promise<{ favorite: boolean }> {
    return requestV1(`/catalog/exercises/${encodeURIComponent(exerciseId)}/favorite`, {
      method: favorite ? 'PUT' : 'DELETE',
    })
  },

  createDraft(input: WorkoutDraftCreate): Promise<WorkoutDraft> {
    return requestV1('/workout-drafts', {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },

  findLatestDraft(logDate: string): Promise<WorkoutDraft | null> {
    const params = new URLSearchParams({ date: logDate })
    return requestV1(`/workout-drafts?${params.toString()}`)
  },

  getDraft(draftId: string): Promise<WorkoutDraft> {
    return requestV1(`/workout-drafts/${encodeURIComponent(draftId)}`)
  },

  updateDraft(
    draftId: string,
    version: number,
    input: WorkoutDraftCreate,
  ): Promise<WorkoutDraft> {
    return requestV1(`/workout-drafts/${encodeURIComponent(draftId)}`, {
      method: 'PATCH',
      headers: { 'If-Match': String(version) },
      body: JSON.stringify(input),
    })
  },

  deleteDraft(draftId: string): Promise<{ deleted: boolean }> {
    return requestV1(`/workout-drafts/${encodeURIComponent(draftId)}`, {
      method: 'DELETE',
    })
  },

  confirmDraft(
    draftId: string,
    version: number,
    idempotencyKey: string,
  ): Promise<ConfirmedWorkout> {
    return requestV1(`/workout-drafts/${encodeURIComponent(draftId)}/confirm`, {
      method: 'POST',
      headers: {
        'If-Match': String(version),
        'Idempotency-Key': idempotencyKey,
      },
    })
  },
}
