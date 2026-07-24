import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  DailyTargetVersion,
  OverallGoalVersion,
  ProfileSetup,
  ProfileSetupMutation,
  ProfileVersion,
  TargetPreview,
  UserProfile,
} from '../types'
import { Profile } from './Profile'


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
  targets: { calories: 2100, carbs: 270, protein: 130, fat: 55 },
  source: 'deterministic_calculation',
  formula_version: 'mifflin_st_jeor_v1',
  warnings: [],
  requires_confirmation: false,
  preview_token: 'a'.repeat(64),
}

const manualPreview: TargetPreview = {
  ...preview,
  targets: { calories: 2172, carbs: 291, protein: 126, fat: 56 },
  source: 'manual',
  formula_version: null,
  warnings: ['TARGET_BASELINE_DEVIATION'],
  requires_confirmation: true,
  preview_token: 'b'.repeat(64),
}

const setup: ProfileSetup = { profile, goal, target, setup_complete: true }

const legacyProfile: UserProfile = {
  height_cm: 175,
  weight_kg: 70,
  age: 30,
  gender: 'male',
  goal: 'fat_loss',
  weekly_training_frequency: 3,
  diet_preferences: [],
  allergies_or_restrictions: [],
  target_weight_kg: 68,
  daily_calorie_target: 2172,
  daily_protein_target: 126,
  experience_level: 'novice',
  training_preference: 'mixed',
  target_mode: 'suggested',
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

const mocks = vi.hoisted(() => ({
  updateProfile: vi.fn(),
  updateOverallGoal: vi.fn(),
  calculateTargets: vi.fn(),
  confirmTargets: vi.fn(),
  saveLegacyProfile: vi.fn(),
  targetHistory: vi.fn(),
  legacyError: null as string | null,
}))

vi.mock('../hooks/usePreferences', () => ({
  usePreferences: () => ({ preferences: { unit_system: 'metric' } }),
}))

vi.mock('../hooks/useProfileSetup', () => ({
  useProfileSetup: () => {
    const [currentSetup, setCurrentSetup] = useState(setup)
    const [currentPreview, setCurrentPreview] = useState<TargetPreview | null>(null)
    const [stalePreview, setStalePreview] = useState(false)

    return {
      setup: currentSetup,
      preview: currentPreview,
      restriction: null,
      loading: false,
      saving: false,
      calculating: false,
      confirming: false,
      stalePreview,
      error: null,
      refresh: vi.fn(),
      updateProfile: async (payload: unknown) => {
        const mutation = await mocks.updateProfile(payload) as ProfileSetupMutation
        setCurrentSetup((current) => ({
          profile: mutation.profile,
          goal: mutation.goal,
          target: current.target,
          setup_complete: true,
        }))
        setCurrentPreview(mutation.recalculation_preview)
        return mutation
      },
      updateOverallGoal: async (payload: unknown) => {
        const mutation = await mocks.updateOverallGoal(payload) as ProfileSetupMutation
        setCurrentSetup((current) => ({
          profile: mutation.profile,
          goal: mutation.goal,
          target: current.target,
          setup_complete: true,
        }))
        setCurrentPreview(mutation.recalculation_preview)
        return mutation
      },
      calculateTargets: async (values?: unknown) => {
        const result = await mocks.calculateTargets(values) as TargetPreview
        setCurrentPreview(result)
        setStalePreview(false)
        return result
      },
      confirmTargets: async (payload: unknown) => {
        const result = await mocks.confirmTargets(payload) as DailyTargetVersion
        setCurrentSetup((current) => ({ ...current, target: result }))
        setCurrentPreview(null)
        return result
      },
    }
  },
}))

vi.mock('../hooks/useProfile', () => ({
  useProfile: () => ({
    profile: legacyProfile,
    setProfile: vi.fn(),
    loading: false,
    saving: false,
    error: mocks.legacyError,
    save: mocks.saveLegacyProfile,
  }),
}))

vi.mock('../services/api', () => ({
  api: {
    targetHistory: mocks.targetHistory,
  },
}))

vi.mock('../components/CoachPanel', () => ({
  CoachPanel: () => <div>Coach advice panel</div>,
}))

describe('Profile', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.legacyError = null
    mocks.targetHistory.mockResolvedValue([target])
    mocks.updateProfile.mockResolvedValue({
      profile: { ...profile, weight_kg: 71 },
      goal,
      recalculation_preview: preview,
      recalculation_restriction: null,
    })
    mocks.updateOverallGoal.mockResolvedValue({
      profile,
      goal: { ...goal, goal: 'maintenance' },
      recalculation_preview: preview,
      recalculation_restriction: null,
    })
    mocks.calculateTargets.mockResolvedValue(manualPreview)
    mocks.confirmTargets.mockResolvedValue({ ...target, ...manualPreview.targets, id: 'target-2', source: 'manual' })
  })

  it('separates body profile, overall goal, daily targets, and legacy personalization', async () => {
    render(<Profile />)

    expect(screen.getByRole('heading', { name: 'Body profile' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Overall goal' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Daily targets' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Training personalization' })).toBeInTheDocument()
    const historyItem = (await screen.findByText('Jul 23, 2026')).closest('li')
    expect(historyItem).toHaveTextContent('2172 kcal')
    expect(historyItem).toHaveTextContent('291 g')
    expect(historyItem).toHaveTextContent('126 g')
    expect(historyItem).toHaveTextContent('56 g')
  })

  it('shows recalculation preview after profile save without confirming it', async () => {
    const user = userEvent.setup()
    render(<Profile />)

    await user.clear(screen.getByLabelText('Weight (kg)'))
    await user.type(screen.getByLabelText('Weight (kg)'), '71')
    await user.click(screen.getByRole('button', { name: 'Save body profile' }))

    expect(mocks.updateProfile).toHaveBeenCalled()
    expect(await screen.findByText('Pending confirmation')).toBeInTheDocument()
    expect(mocks.confirmTargets).not.toHaveBeenCalled()
  })

  it('saves the overall goal as a preview without confirming it', async () => {
    const user = userEvent.setup()
    render(<Profile />)

    await user.click(screen.getByLabelText('Maintenance'))
    await user.click(screen.getByRole('button', { name: 'Save overall goal' }))

    expect(mocks.updateOverallGoal).toHaveBeenCalledWith(expect.objectContaining({ goal: 'maintenance' }))
    expect(await screen.findByText('Pending confirmation')).toBeInTheDocument()
    expect(mocks.confirmTargets).not.toHaveBeenCalled()
  })

  it('preserves an unsaved body draft when the overall goal is saved', async () => {
    const user = userEvent.setup()
    mocks.updateOverallGoal.mockResolvedValue({
      profile: { ...profile },
      goal: { ...goal, id: 'goal-2', goal: 'maintenance' },
      recalculation_preview: preview,
      recalculation_restriction: null,
    })
    render(<Profile />)

    await user.clear(screen.getByLabelText('Weight (kg)'))
    await user.type(screen.getByLabelText('Weight (kg)'), '72')
    await user.click(screen.getByLabelText('Maintenance'))
    await user.click(screen.getByRole('button', { name: 'Save overall goal' }))

    await waitFor(() => expect(mocks.updateOverallGoal).toHaveBeenCalled())
    expect(screen.getByLabelText('Weight (kg)')).toHaveValue(72)
  })

  it('preserves an unsaved goal draft when the body profile is saved', async () => {
    const user = userEvent.setup()
    mocks.updateProfile.mockResolvedValue({
      profile: { ...profile, id: 'profile-2', weight_kg: 71 },
      goal: { ...goal },
      recalculation_preview: preview,
      recalculation_restriction: null,
    })
    render(<Profile />)

    await user.click(screen.getByLabelText('Maintenance'))
    await user.clear(screen.getByLabelText('Weight (kg)'))
    await user.type(screen.getByLabelText('Weight (kg)'), '71')
    await user.click(screen.getByRole('button', { name: 'Save body profile' }))

    await waitFor(() => expect(mocks.updateProfile).toHaveBeenCalled())
    expect(screen.getByLabelText('Maintenance')).toBeChecked()
  })

  it('requires warning acknowledgement before confirming manual targets', async () => {
    const user = userEvent.setup()
    render(<Profile />)

    await user.click(screen.getByLabelText('Set targets manually'))
    await user.click(screen.getByRole('button', { name: 'Review manual targets' }))

    const confirm = await screen.findByRole('button', { name: 'Confirm daily targets' })
    expect(confirm).toBeDisabled()

    await user.click(screen.getByLabelText('I reviewed these warnings and want to continue.'))
    expect(confirm).toBeEnabled()
    await user.click(confirm)

    await waitFor(() => expect(mocks.confirmTargets).toHaveBeenCalledTimes(1))
  })

  it('invalidates an acknowledged preview when a manual value changes', async () => {
    const user = userEvent.setup()
    const recalculatedPreview = {
      ...manualPreview,
      targets: { ...manualPreview.targets, calories: 2600 },
      preview_token: 'c'.repeat(64),
    }
    mocks.calculateTargets
      .mockResolvedValueOnce(manualPreview)
      .mockResolvedValueOnce(recalculatedPreview)
    render(<Profile />)

    await user.click(screen.getByLabelText('Set targets manually'))
    await user.click(screen.getByRole('button', { name: 'Review manual targets' }))
    await user.click(await screen.findByLabelText('I reviewed these warnings and want to continue.'))
    expect(screen.getByRole('button', { name: 'Confirm daily targets' })).toBeEnabled()

    await user.clear(screen.getByLabelText('Calories (kcal)'))
    await user.type(screen.getByLabelText('Calories (kcal)'), '2600')

    expect(screen.queryByRole('button', { name: 'Confirm daily targets' })).not.toBeInTheDocument()
    expect(mocks.confirmTargets).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Review manual targets' }))
    const confirm = await screen.findByRole('button', { name: 'Confirm daily targets' })
    expect(confirm).toBeDisabled()
    await user.click(screen.getByLabelText('I reviewed these warnings and want to continue.'))
    expect(confirm).toBeEnabled()
  })

  it('requires manual recalculation when a deterministic preview arrives in manual mode', async () => {
    const user = userEvent.setup()
    const matchingManualPreview = {
      ...manualPreview,
      targets: { calories: 2400, carbs: 291, protein: 126, fat: 56 },
      preview_token: 'd'.repeat(64),
    }
    mocks.calculateTargets.mockResolvedValueOnce(matchingManualPreview)
    render(<Profile />)

    await user.click(screen.getByLabelText('Set targets manually'))
    await user.clear(screen.getByLabelText('Calories (kcal)'))
    await user.type(screen.getByLabelText('Calories (kcal)'), '2400')
    await user.click(screen.getByRole('button', { name: 'Save body profile' }))
    await waitFor(() => expect(mocks.updateProfile).toHaveBeenCalled())

    expect(screen.queryByRole('button', { name: 'Confirm daily targets' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Review manual targets' }))
    expect(mocks.calculateTargets).toHaveBeenCalledWith({
      calories: 2400,
      carbs: 291,
      protein: 126,
      fat: 56,
    })
    expect(await screen.findByRole('button', { name: 'Confirm daily targets' })).toBeDisabled()
  })

  it('reuses effectiveFrom when confirmation reload fails and the same preview is retried', async () => {
    const user = userEvent.setup()
    mocks.confirmTargets
      .mockRejectedValueOnce(new Error('Aggregate unavailable'))
      .mockResolvedValueOnce({ ...target, ...manualPreview.targets, id: 'target-2', source: 'manual' })
    render(<Profile />)

    await user.click(screen.getByLabelText('Set targets manually'))
    await user.click(screen.getByRole('button', { name: 'Review manual targets' }))
    await user.click(await screen.findByLabelText('I reviewed these warnings and want to continue.'))

    const confirm = screen.getByRole('button', { name: 'Confirm daily targets' })
    await user.click(confirm)
    await waitFor(() => expect(mocks.confirmTargets).toHaveBeenCalledTimes(1))

    await user.click(confirm)
    await waitFor(() => expect(mocks.confirmTargets).toHaveBeenCalledTimes(2))

    const firstEffectiveFrom = mocks.confirmTargets.mock.calls[0][0].effectiveFrom
    const retryEffectiveFrom = mocks.confirmTargets.mock.calls[1][0].effectiveFrom
    expect(retryEffectiveFrom).toBe(firstEffectiveFrom)
  })

  it('keeps post-confirm history when the initial history request resolves last', async () => {
    const user = userEvent.setup()
    const initialHistory = deferred<DailyTargetVersion[]>()
    const calculatedPreview = {
      ...manualPreview,
      targets: { ...manualPreview.targets, calories: 2500 },
      preview_token: 'e'.repeat(64),
    }
    const confirmedTarget = {
      ...target,
      ...calculatedPreview.targets,
      id: 'target-2',
      source: 'manual' as const,
    }
    mocks.targetHistory
      .mockReset()
      .mockReturnValueOnce(initialHistory.promise)
      .mockResolvedValueOnce([confirmedTarget])
    mocks.calculateTargets.mockResolvedValueOnce(calculatedPreview)
    mocks.confirmTargets.mockResolvedValue(confirmedTarget)
    render(<Profile />)

    await user.click(screen.getByLabelText('Set targets manually'))
    await user.clear(screen.getByLabelText('Calories (kcal)'))
    await user.type(screen.getByLabelText('Calories (kcal)'), '2500')
    await user.click(screen.getByRole('button', { name: 'Review manual targets' }))
    await user.click(await screen.findByLabelText('I reviewed these warnings and want to continue.'))
    await user.click(screen.getByRole('button', { name: 'Confirm daily targets' }))

    await waitFor(() => expect(mocks.targetHistory).toHaveBeenCalledTimes(2))
    const history = screen.getByText('Target history').closest('details')
    await waitFor(() => expect(history?.querySelector('li')).toHaveTextContent('2500 kcal'))

    await act(async () => {
      initialHistory.resolve([target])
      await initialHistory.promise
    })
    expect(history?.querySelector('li')).toHaveTextContent('2500 kcal')
    expect(history?.querySelector('li')).not.toHaveTextContent('2172 kcal')
  })

  it('does not reload target history when confirmation finishes after unmount', async () => {
    const user = userEvent.setup()
    const confirmation = deferred<DailyTargetVersion>()
    mocks.confirmTargets.mockReturnValueOnce(confirmation.promise)
    const { unmount } = render(<Profile />)

    await waitFor(() => expect(mocks.targetHistory).toHaveBeenCalledTimes(1))
    await user.click(screen.getByLabelText('Set targets manually'))
    await user.click(screen.getByRole('button', { name: 'Review manual targets' }))
    await user.click(await screen.findByLabelText('I reviewed these warnings and want to continue.'))
    await user.click(screen.getByRole('button', { name: 'Confirm daily targets' }))
    await waitFor(() => expect(mocks.confirmTargets).toHaveBeenCalledTimes(1))

    unmount()
    await act(async () => {
      confirmation.resolve({ ...target, id: 'target-2' })
      await confirmation.promise
    })

    expect(mocks.targetHistory).toHaveBeenCalledTimes(1)
  })

  it('saves legacy training fields without invoking versioned profile writes', async () => {
    const user = userEvent.setup()
    render(<Profile />)

    await user.selectOptions(screen.getByLabelText('Experience'), 'experienced')
    await user.click(screen.getByRole('button', { name: 'Save training personalization' }))

    expect(mocks.saveLegacyProfile).toHaveBeenCalledWith(expect.objectContaining({
      experience_level: 'experienced',
      training_preference: 'mixed',
    }))
    expect(mocks.updateProfile).not.toHaveBeenCalled()
  })

  it('shows a local error when reading the legacy profile fails', async () => {
    mocks.legacyError = 'Legacy profile unavailable'
    render(<Profile />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Legacy profile unavailable')
    expect(mocks.saveLegacyProfile).not.toHaveBeenCalled()
  })

  it('shows a local error when saving legacy personalization fails', async () => {
    const user = userEvent.setup()
    mocks.saveLegacyProfile.mockRejectedValueOnce(new Error('Legacy profile save failed'))
    render(<Profile />)

    await user.click(screen.getByRole('button', { name: 'Save training personalization' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Legacy profile save failed')
  })

  it('locks concurrent training personalization saves', async () => {
    const save = deferred<void>()
    mocks.saveLegacyProfile.mockReturnValueOnce(save.promise)
    render(<Profile />)

    const submit = screen.getByRole('button', { name: 'Save training personalization' })
    act(() => {
      submit.click()
      submit.click()
    })

    expect(mocks.saveLegacyProfile).toHaveBeenCalledTimes(1)
    expect(submit).toBeDisabled()
    expect(screen.getByLabelText('Experience')).toBeDisabled()
    expect(screen.getByLabelText('Training focus')).toBeDisabled()

    await act(async () => {
      save.resolve()
      await save.promise
    })
    await waitFor(() => expect(submit).toBeEnabled())
  })

  it('states that Coach target analysis is advice only', () => {
    render(<Profile />)

    expect(screen.getByText('Coach analysis is advice only and never changes saved targets.')).toBeInTheDocument()
  })
})
