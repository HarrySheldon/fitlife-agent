import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiRequestError, api } from '../services/api'
import type {
  DailyTargetVersion,
  OverallGoalVersionUpdate,
  OverallGoalVersion,
  ProfileSetup,
  ProfileSetupMutation,
  ProfileVersionUpdate,
  ProfileVersion,
  TargetPreview,
} from '../types'
import { useProfileSetup } from './useProfileSetup'


vi.mock('../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/api')>()
  return {
    ...original,
    api: {
      ...original.api,
      profileSetup: vi.fn(),
      saveProfileVersion: vi.fn(),
      saveOverallGoal: vi.fn(),
      calculateTargets: vi.fn(),
      confirmTargets: vi.fn(),
      targetHistory: vi.fn(),
    },
  }
})

const profile: ProfileVersion = {
  id: 'profile-1',
  user_id: 'user-1',
  age: 30,
  height_cm: 175,
  weight_kg: 70,
  energy_parameter: 'male',
  activity_level: 'moderate',
  auto_target_disabled: false,
  safety_conditions: [],
  effective_from: '2026-07-23T08:00:00Z',
  created_at: '2026-07-23T08:00:00Z',
}

const goal: OverallGoalVersion = {
  id: 'goal-1',
  user_id: 'user-1',
  goal: 'fat_loss',
  effective_from: '2026-07-23T08:00:00Z',
  created_at: '2026-07-23T08:00:00Z',
}

const target: DailyTargetVersion = {
  id: 'target-1',
  user_id: 'user-1',
  profile_version_id: profile.id,
  overall_goal_version_id: goal.id,
  calories: 2172,
  carbs: 291,
  protein: 126,
  fat: 56,
  source: 'deterministic_calculation',
  formula_version: 'mifflin_st_jeor_v1',
  rationale: {},
  effective_from: '2026-07-23T09:00:00Z',
  created_at: '2026-07-23T09:00:00Z',
}

const preview: TargetPreview = {
  profile_version_id: profile.id,
  overall_goal_version_id: goal.id,
  targets: { calories: 2172, carbs: 291, protein: 126, fat: 56 },
  source: 'deterministic_calculation',
  formula_version: 'mifflin_st_jeor_v1',
  warnings: [],
  requires_confirmation: false,
  preview_token: 'a'.repeat(64),
}

const completeSetup: ProfileSetup = {
  profile,
  goal,
  target,
  setup_complete: true,
}

const profileUpdate: ProfileVersionUpdate = {
  age: profile.age,
  height_cm: profile.height_cm,
  weight_kg: profile.weight_kg,
  energy_parameter: profile.energy_parameter,
  activity_level: profile.activity_level,
  auto_target_disabled: profile.auto_target_disabled,
  safety_conditions: profile.safety_conditions,
  effective_from: profile.effective_from,
}

const goalUpdate: OverallGoalVersionUpdate = {
  goal: goal.goal,
  effective_from: goal.effective_from,
}

const confirmationInput = {
  effectiveFrom: '2026-07-23T09:00:00Z',
  acknowledgeWarnings: false,
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.mocked(api.profileSetup).mockReset()
  vi.mocked(api.saveProfileVersion).mockReset()
  vi.mocked(api.saveOverallGoal).mockReset()
  vi.mocked(api.calculateTargets).mockReset()
  vi.mocked(api.confirmTargets).mockReset()
  vi.mocked(api.targetHistory).mockReset()
})

describe('useProfileSetup', () => {
  it('loads the profile setup aggregate on mount', async () => {
    vi.mocked(api.profileSetup).mockResolvedValue(completeSetup)

    const { result } = renderHook(() => useProfileSetup())

    expect(result.current.loading).toBe(true)
    await waitFor(() => expect(result.current.setup).toEqual(completeSetup))
    expect(result.current.loading).toBe(false)
    expect(result.current.error).toBeNull()
  })

  it('replaces the current preview after profile and goal updates', async () => {
    const firstPreview = { ...preview, preview_token: 'b'.repeat(64) }
    const secondPreview = { ...preview, preview_token: 'c'.repeat(64) }
    vi.mocked(api.profileSetup).mockResolvedValue({
      profile: null,
      goal: null,
      target: null,
      setup_complete: false,
    })
    vi.mocked(api.saveProfileVersion).mockResolvedValue({
      profile,
      goal: null,
      recalculation_preview: firstPreview,
      recalculation_restriction: null,
    })
    vi.mocked(api.saveOverallGoal).mockResolvedValue({
      profile,
      goal,
      recalculation_preview: secondPreview,
      recalculation_restriction: null,
    })
    const { result } = renderHook(() => useProfileSetup())
    await waitFor(() => expect(result.current.loading).toBe(false))

    await act(() => result.current.updateProfile(profileUpdate))

    expect(result.current.setup?.profile).toEqual(profile)
    expect(result.current.preview).toEqual(firstPreview)

    await act(() => result.current.updateOverallGoal(goalUpdate))

    expect(result.current.setup?.goal).toEqual(goal)
    expect(result.current.preview).toEqual(secondPreview)
    expect(result.current.preview).not.toEqual(firstPreview)
  })

  it('confirms the current preview with a UUID and refetches the aggregate', async () => {
    const incompleteSetup: ProfileSetup = {
      profile,
      goal,
      target: null,
      setup_complete: false,
    }
    vi.mocked(api.profileSetup)
      .mockResolvedValueOnce(incompleteSetup)
      .mockResolvedValueOnce(completeSetup)
    vi.mocked(api.calculateTargets).mockResolvedValue(preview)
    vi.mocked(api.confirmTargets).mockResolvedValue({ target })
    const randomUUID = vi.spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValue('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
    const { result } = renderHook(() => useProfileSetup())
    await waitFor(() => expect(result.current.loading).toBe(false))

    await act(() => result.current.calculateTargets())
    expect(result.current.preview).toEqual(preview)

    await act(() => result.current.confirmTargets({
      effectiveFrom: '2026-07-23T09:00:00Z',
      acknowledgeWarnings: false,
    }))

    expect(randomUUID).toHaveBeenCalledOnce()
    expect(api.confirmTargets).toHaveBeenCalledWith({
      preview,
      effective_from: '2026-07-23T09:00:00Z',
      acknowledge_warnings: false,
      idempotencyKey: '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
    })
    expect(api.profileSetup).toHaveBeenCalledTimes(2)
    expect(result.current.setup).toEqual(completeSetup)
    expect(result.current.preview).toBeNull()
  })

  it('marks a stale confirmation error and discards the invalid preview', async () => {
    vi.mocked(api.profileSetup).mockResolvedValue({
      profile,
      goal,
      target: null,
      setup_complete: false,
    })
    vi.mocked(api.calculateTargets).mockResolvedValue(preview)
    vi.mocked(api.confirmTargets).mockRejectedValue(
      new ApiRequestError('Preview is stale.', 'TARGET_PREVIEW_STALE', 'deterministic', 412),
    )
    vi.spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValue('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
    const { result } = renderHook(() => useProfileSetup())
    await waitFor(() => expect(result.current.loading).toBe(false))
    await act(() => result.current.calculateTargets())

    await act(async () => {
      await expect(result.current.confirmTargets({
        effectiveFrom: '2026-07-23T09:00:00Z',
        acknowledgeWarnings: false,
      })).rejects.toMatchObject({ code: 'TARGET_PREVIEW_STALE', status: 412 })
    })

    expect(result.current.stalePreview).toBe(true)
    expect(result.current.preview).toBeNull()
    expect(result.current.error).toBe('Preview is stale.')
    expect(api.profileSetup).toHaveBeenCalledOnce()
  })

  it('reuses the idempotency key for an unknown-error retry and rotates it when the request changes', async () => {
    vi.mocked(api.profileSetup).mockResolvedValue({
      profile,
      goal,
      target: null,
      setup_complete: false,
    })
    vi.mocked(api.calculateTargets).mockResolvedValue(preview)
    vi.mocked(api.confirmTargets).mockRejectedValue(new TypeError('Network unavailable'))
    const randomUUID = vi.spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValueOnce('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
      .mockReturnValueOnce('6ba7b811-9dad-11d1-80b4-00c04fd430c8')
    const { result } = renderHook(() => useProfileSetup())
    await waitFor(() => expect(result.current.loading).toBe(false))
    await act(() => result.current.calculateTargets())

    for (let attempt = 0; attempt < 2; attempt += 1) {
      await act(async () => {
        await expect(result.current.confirmTargets(confirmationInput))
          .rejects.toThrow('Network unavailable')
      })
    }
    await act(async () => {
      await expect(result.current.confirmTargets({
        ...confirmationInput,
        acknowledgeWarnings: true,
      })).rejects.toThrow('Network unavailable')
    })

    expect(randomUUID).toHaveBeenCalledTimes(2)
    expect(vi.mocked(api.confirmTargets).mock.calls.map(([request]) => request.idempotencyKey)).toEqual([
      '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
      '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
      '6ba7b811-9dad-11d1-80b4-00c04fd430c8',
    ])
  })

  it('keeps the key when confirmation succeeds but aggregate refetch fails', async () => {
    vi.mocked(api.profileSetup)
      .mockResolvedValueOnce({
        profile,
        goal,
        target: null,
        setup_complete: false,
      })
      .mockRejectedValueOnce(new TypeError('Aggregate unavailable'))
      .mockResolvedValue(completeSetup)
    vi.mocked(api.calculateTargets).mockResolvedValue(preview)
    vi.mocked(api.confirmTargets).mockResolvedValue({ target })
    const randomUUID = vi.spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValueOnce('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
      .mockReturnValueOnce('6ba7b811-9dad-11d1-80b4-00c04fd430c8')
    const { result } = renderHook(() => useProfileSetup())
    await waitFor(() => expect(result.current.loading).toBe(false))
    await act(() => result.current.calculateTargets())

    await act(async () => {
      await expect(result.current.confirmTargets(confirmationInput))
        .rejects.toThrow('Aggregate unavailable')
    })
    await act(() => result.current.confirmTargets(confirmationInput))

    expect(vi.mocked(api.confirmTargets).mock.calls.slice(0, 2).map(([request]) => request.idempotencyKey)).toEqual([
      '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
      '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
    ])

    await act(() => result.current.calculateTargets())
    await act(() => result.current.confirmTargets(confirmationInput))

    expect(randomUUID).toHaveBeenCalledTimes(2)
    expect(vi.mocked(api.confirmTargets).mock.calls[2][0].idempotencyKey)
      .toBe('6ba7b811-9dad-11d1-80b4-00c04fd430c8')
  })

  it('rotates the key when the preview changes and after a stale response', async () => {
    const replacementPreview = {
      ...preview,
      targets: { ...preview.targets, calories: 2200 },
      preview_token: 'd'.repeat(64),
    }
    vi.mocked(api.profileSetup).mockResolvedValue({
      profile,
      goal,
      target: null,
      setup_complete: false,
    })
    vi.mocked(api.calculateTargets)
      .mockResolvedValueOnce(preview)
      .mockResolvedValueOnce(replacementPreview)
      .mockResolvedValueOnce(replacementPreview)
    vi.mocked(api.confirmTargets)
      .mockRejectedValueOnce(new TypeError('Network unavailable'))
      .mockRejectedValueOnce(
        new ApiRequestError('Preview is stale.', 'TARGET_PREVIEW_STALE', 'deterministic', 412),
      )
      .mockRejectedValueOnce(new TypeError('Network unavailable'))
    const randomUUID = vi.spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValueOnce('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
      .mockReturnValueOnce('6ba7b811-9dad-11d1-80b4-00c04fd430c8')
      .mockReturnValueOnce('6ba7b812-9dad-11d1-80b4-00c04fd430c8')
    const { result } = renderHook(() => useProfileSetup())
    await waitFor(() => expect(result.current.loading).toBe(false))

    await act(() => result.current.calculateTargets())
    await act(async () => {
      await expect(result.current.confirmTargets(confirmationInput))
        .rejects.toThrow('Network unavailable')
    })
    await act(() => result.current.calculateTargets())
    await act(async () => {
      await expect(result.current.confirmTargets(confirmationInput))
        .rejects.toMatchObject({ code: 'TARGET_PREVIEW_STALE' })
    })
    await act(() => result.current.calculateTargets())
    await act(async () => {
      await expect(result.current.confirmTargets(confirmationInput))
        .rejects.toThrow('Network unavailable')
    })

    expect(randomUUID).toHaveBeenCalledTimes(3)
    expect(vi.mocked(api.confirmTargets).mock.calls.map(([request]) => request.idempotencyKey)).toEqual([
      '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
      '6ba7b811-9dad-11d1-80b4-00c04fd430c8',
      '6ba7b812-9dad-11d1-80b4-00c04fd430c8',
    ])
  })

  it('does not start a goal save while a profile save is active', async () => {
    const activeSave = deferred<ProfileSetupMutation>()
    vi.mocked(api.profileSetup).mockResolvedValue(completeSetup)
    vi.mocked(api.saveProfileVersion).mockReturnValue(activeSave.promise)
    const { result } = renderHook(() => useProfileSetup())
    await waitFor(() => expect(result.current.loading).toBe(false))

    let profileRequest!: Promise<ProfileSetupMutation>
    let overlappingGoalRequest!: Promise<ProfileSetupMutation>
    act(() => {
      profileRequest = result.current.updateProfile(profileUpdate)
      overlappingGoalRequest = result.current.updateOverallGoal(goalUpdate)
    })

    await expect(overlappingGoalRequest).rejects.toThrow('PROFILE_SETUP_OPERATION_IN_PROGRESS')
    expect(api.saveProfileVersion).toHaveBeenCalledOnce()
    expect(api.saveOverallGoal).not.toHaveBeenCalled()
    expect(result.current.saving).toBe(true)
    expect(result.current.calculating).toBe(false)
    expect(result.current.confirming).toBe(false)

    await act(async () => {
      activeSave.resolve({
        profile,
        goal,
        recalculation_preview: preview,
        recalculation_restriction: null,
      })
      await profileRequest
    })

    expect(result.current.saving).toBe(false)
    expect(result.current.preview).toEqual(preview)
  })

  it('does not start a calculation while target confirmation is active', async () => {
    const confirmation = deferred<{ target: DailyTargetVersion }>()
    vi.mocked(api.profileSetup)
      .mockResolvedValueOnce({
        profile,
        goal,
        target: null,
        setup_complete: false,
      })
      .mockResolvedValue(completeSetup)
    vi.mocked(api.calculateTargets).mockResolvedValue(preview)
    vi.mocked(api.confirmTargets).mockReturnValue(confirmation.promise)
    vi.spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValue('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
    const { result } = renderHook(() => useProfileSetup())
    await waitFor(() => expect(result.current.loading).toBe(false))
    await act(() => result.current.calculateTargets())

    let confirmationRequest!: Promise<DailyTargetVersion>
    let overlappingCalculation!: Promise<TargetPreview>
    act(() => {
      confirmationRequest = result.current.confirmTargets(confirmationInput)
      overlappingCalculation = result.current.calculateTargets({
        calories: 2172,
        carbs: 285,
        protein: 132,
        fat: 56,
      })
    })

    await expect(overlappingCalculation).rejects.toThrow('PROFILE_SETUP_OPERATION_IN_PROGRESS')
    expect(api.confirmTargets).toHaveBeenCalledOnce()
    expect(api.calculateTargets).toHaveBeenCalledOnce()
    expect(result.current.confirming).toBe(true)
    expect(result.current.calculating).toBe(false)
    expect(result.current.preview).toEqual(preview)

    await act(async () => {
      confirmation.resolve({ target })
      await confirmationRequest
    })

    expect(result.current.preview).toBeNull()
    expect(result.current.confirming).toBe(false)
  })

  it('sets loading and error consistently when refresh fails', async () => {
    const refresh = deferred<ProfileSetup>()
    vi.mocked(api.profileSetup)
      .mockResolvedValueOnce(completeSetup)
      .mockReturnValueOnce(refresh.promise)
    const { result } = renderHook(() => useProfileSetup())
    await waitFor(() => expect(result.current.loading).toBe(false))

    let refreshRequest!: Promise<ProfileSetup>
    act(() => {
      refreshRequest = result.current.refresh()
    })

    expect(result.current.loading).toBe(true)
    expect(result.current.error).toBeNull()

    await act(async () => {
      const rejected = expect(refreshRequest).rejects.toThrow('Refresh unavailable')
      refresh.reject(new TypeError('Refresh unavailable'))
      await rejected
    })

    expect(result.current.loading).toBe(false)
    expect(result.current.error).toBe('Refresh unavailable')
    expect(result.current.setup).toEqual(completeSetup)
  })
})
