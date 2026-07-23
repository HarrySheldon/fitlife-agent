import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  AuthenticatedUser,
  OverallGoalVersion,
  ProfileSetup,
  ProfileSetupMutation,
  ProfileVersion,
  TargetPreview,
} from '../types'
import { ApiRequestError } from '../services/api'
import { OnboardingGate } from '../components/OnboardingGate'
import { Auth } from './Auth'
import { Onboarding } from './Onboarding'


const ONBOARDING_END_TO_END_TIMEOUT_MS = 15_000

const profile: ProfileVersion = {
  id: 'profile-1',
  user_id: 'user-1',
  age: 34,
  height_cm: 176,
  weight_kg: 74,
  energy_parameter: 'neutral',
  activity_level: 'moderate',
  auto_target_disabled: false,
  safety_conditions: [],
  effective_from: '2026-07-23T00:00:00Z',
  created_at: '2026-07-23T00:00:00Z',
}

const goal: OverallGoalVersion = {
  id: 'goal-1',
  user_id: 'user-1',
  goal: 'fat_loss',
  effective_from: '2026-07-23T00:00:00Z',
  created_at: '2026-07-23T00:00:00Z',
}

const deterministicPreview: TargetPreview = {
  profile_version_id: profile.id,
  overall_goal_version_id: goal.id,
  targets: { calories: 2172, carbs: 291, protein: 126, fat: 56 },
  source: 'deterministic_calculation',
  formula_version: 'mifflin_st_jeor_v1',
  warnings: [],
  requires_confirmation: false,
  preview_token: 'a'.repeat(64),
}

const manualPreview: TargetPreview = {
  ...deterministicPreview,
  targets: { calories: 2400, carbs: 250, protein: 150, fat: 70 },
  source: 'manual',
  formula_version: null,
  warnings: ['TARGET_BASELINE_DEVIATION'],
  requires_confirmation: true,
  preview_token: 'b'.repeat(64),
}

const onboarding = vi.hoisted(() => ({
  initialSetup: null as ProfileSetup | null,
  initialRestriction: null as string | null,
  updateProfile: vi.fn(),
  updateOverallGoal: vi.fn(),
  calculateTargets: vi.fn(),
  confirmTargets: vi.fn(),
}))

const auth = vi.hoisted(() => ({
  user: null as AuthenticatedUser | null,
  login: vi.fn(),
  register: vi.fn(),
}))

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => {
    const [user, setUser] = useState(auth.user)
    const authenticatedUser: AuthenticatedUser = {
      user_id: 'user-1',
      username: 'harry',
      email: null,
      phone: null,
      display_name: 'Harry',
    }

    return {
      user,
      initializing: false,
      login: async (payload: unknown) => {
        await auth.login(payload)
        setUser(authenticatedUser)
      },
      register: async (payload: unknown) => {
        await auth.register(payload)
        setUser(authenticatedUser)
      },
    }
  },
}))

vi.mock('../hooks/useProfileSetup', async () => {
  return {
    useProfileSetup: () => {
      const [setup, setSetup] = useState(onboarding.initialSetup)
      const [preview, setPreview] = useState<TargetPreview | null>(null)
      const [restriction, setRestriction] = useState(onboarding.initialRestriction)
      const [stalePreview, setStalePreview] = useState(false)

      return {
        setup,
        preview,
        restriction,
        loading: false,
        saving: false,
        calculating: false,
        confirming: false,
        stalePreview,
        error: null,
        refresh: vi.fn(),
        updateProfile: async (payload: unknown) => {
          const mutation = await onboarding.updateProfile(payload) as ProfileSetupMutation
          setSetup((current) => ({
            profile: mutation.profile,
            goal: mutation.goal,
            target: current?.target ?? null,
            setup_complete: false,
          }))
          setPreview(mutation.recalculation_preview)
          setRestriction(mutation.recalculation_restriction)
          return mutation
        },
        updateOverallGoal: async (payload: unknown) => {
          const mutation = await onboarding.updateOverallGoal(payload) as ProfileSetupMutation
          setSetup((current) => ({
            profile: mutation.profile,
            goal: mutation.goal,
            target: current?.target ?? null,
            setup_complete: false,
          }))
          setPreview(mutation.recalculation_preview)
          setRestriction(mutation.recalculation_restriction)
          return mutation
        },
        calculateTargets: async (targets?: unknown) => {
          const result = await onboarding.calculateTargets(targets) as TargetPreview
          setPreview(result)
          setRestriction(null)
          setStalePreview(false)
          return result
        },
        confirmTargets: async (payload: unknown) => {
          try {
            const result = await onboarding.confirmTargets(payload)
            setSetup((current) => current ? { ...current, target: result, setup_complete: true } : current)
            return result
          } catch (cause) {
            if (
              cause instanceof ApiRequestError
              && (cause.code === 'TARGET_PREVIEW_STALE' || cause.status === 412)
            ) {
              setPreview(null)
              setStalePreview(true)
            }
            throw cause
          }
        },
      }
    },
  }
})

function LocationProbe() {
  const location = useLocation()
  return <output aria-label="location">{location.pathname}</output>
}

function renderOnboarding() {
  return render(
    <MemoryRouter initialEntries={['/onboarding']}>
      <Routes>
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/" element={<h1>Today workspace</h1>} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  )
}

function profileMutation(overrides: Partial<ProfileSetupMutation> = {}): ProfileSetupMutation {
  return {
    profile,
    goal: null,
    recalculation_preview: null,
    recalculation_restriction: null,
    ...overrides,
  }
}

beforeEach(() => {
  onboarding.initialSetup = { profile, goal: null, target: null, setup_complete: false }
  onboarding.initialRestriction = null
  onboarding.updateProfile.mockReset().mockResolvedValue(profileMutation())
  onboarding.updateOverallGoal.mockReset().mockResolvedValue(profileMutation({
    goal,
    recalculation_preview: deterministicPreview,
  }))
  onboarding.calculateTargets.mockReset().mockResolvedValue(manualPreview)
  onboarding.confirmTargets.mockReset().mockResolvedValue({
    id: 'target-1',
    user_id: 'user-1',
    profile_version_id: profile.id,
    overall_goal_version_id: goal.id,
    source: 'manual',
    formula_version: null,
    rationale: {},
    effective_from: '2026-07-23T00:00:00Z',
    created_at: '2026-07-23T00:00:00Z',
    ...manualPreview.targets,
  })
  auth.user = null
  auth.login.mockReset().mockResolvedValue(undefined)
  auth.register.mockReset().mockResolvedValue(undefined)
  vi.restoreAllMocks()
})

describe('Onboarding', () => {
  it('loads profile values and completes deterministic-to-manual target confirmation', async () => {
    const user = userEvent.setup()
    renderOnboarding()

    expect(await screen.findByRole('heading', { name: 'Your starting profile' })).toBeInTheDocument()
    expect(screen.getByLabelText('Age')).toHaveValue(34)
    expect(screen.getByLabelText('Height (cm)')).toHaveValue(176)
    expect(screen.getByLabelText('Weight (kg)')).toHaveValue(74)
    expect(screen.getByRole('list', { name: 'Setup progress' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByRole('heading', { name: 'Goal and activity' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('radio', { name: 'Fat loss' }))
    fireEvent.change(screen.getByLabelText('Activity level'), { target: { value: 'high' } })
    fireEvent.click(screen.getByRole('button', { name: 'Calculate targets' }))

    expect(await screen.findByRole('heading', { name: 'Daily target preview' })).toBeInTheDocument()
    expect(screen.getByDisplayValue('2172')).toBeInTheDocument()
    expect(screen.getByText('Calculated targets are estimates, not medical advice.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('checkbox', { name: 'Set my own daily targets' }))
    fireEvent.change(screen.getByLabelText('Calories (kcal)'), { target: { value: '2400' } })
    fireEvent.change(screen.getByLabelText('Carbohydrate (g)'), { target: { value: '250' } })
    fireEvent.change(screen.getByLabelText('Protein (g)'), { target: { value: '150' } })
    fireEvent.change(screen.getByLabelText('Fat (g)'), { target: { value: '70' } })
    fireEvent.click(screen.getByRole('button', { name: 'Review targets' }))

    expect(await screen.findByRole('heading', { name: 'Confirm daily targets' })).toBeInTheDocument()
    expect(screen.getByText('2,400 kcal')).toBeInTheDocument()
    expect(screen.getByText('250 g')).toBeInTheDocument()
    expect(screen.getByText('150 g')).toBeInTheDocument()
    expect(screen.getByText('70 g')).toBeInTheDocument()

    const acknowledgement = screen.getByRole('checkbox', { name: 'I reviewed these warnings and want to continue.' })
    expect(acknowledgement).not.toBeChecked()
    fireEvent.click(acknowledgement)
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    fireEvent.change(screen.getByLabelText('Calories (kcal)'), { target: { value: '2450' } })
    onboarding.calculateTargets.mockResolvedValueOnce({
      ...manualPreview,
      targets: { ...manualPreview.targets, calories: 2450 },
      preview_token: 'c'.repeat(64),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Review targets' }))

    const refreshedAcknowledgement = await screen.findByRole('checkbox', {
      name: 'I reviewed these warnings and want to continue.',
    })
    const confirmButton = screen.getByRole('button', { name: 'Confirm and start' })
    expect(refreshedAcknowledgement).not.toBeChecked()
    expect(confirmButton).toBeDisabled()

    await user.click(refreshedAcknowledgement)
    await waitFor(() => expect(confirmButton).toBeEnabled())
    await user.click(confirmButton)

    await waitFor(() => expect(onboarding.confirmTargets).toHaveBeenCalledWith(expect.objectContaining({
      acknowledgeWarnings: true,
    })))
    expect(await screen.findByRole('heading', { name: 'Today workspace' })).toBeInTheDocument()
    expect(screen.getByLabelText('location')).toHaveTextContent('/')
  }, ONBOARDING_END_TO_END_TIMEOUT_MS)

  it('replaces target controls with a medical-care message when calculation is restricted', async () => {
    onboarding.updateOverallGoal.mockResolvedValueOnce(profileMutation({
      goal,
      recalculation_restriction: 'TARGET_CALCULATION_RESTRICTED',
    }))
    renderOnboarding()

    fireEvent.click(await screen.findByRole('button', { name: 'Continue' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Calculate targets' }))

    expect(await screen.findByRole('heading', { name: 'Automatic targets unavailable' })).toBeInTheDocument()
    expect(screen.getByText('Talk with a qualified medical professional before setting nutrition targets.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Calories (kcal)')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Review targets' })).not.toBeInTheDocument()
  })

  it('returns to target review and recalculates after a stale confirmation', async () => {
    const user = userEvent.setup()
    onboarding.confirmTargets.mockRejectedValueOnce(
      new ApiRequestError('Preview is stale.', 'TARGET_PREVIEW_STALE', 'deterministic', 412),
    )
    onboarding.calculateTargets.mockResolvedValueOnce({
      ...deterministicPreview,
      preview_token: 'd'.repeat(64),
    })
    renderOnboarding()

    await user.click(await screen.findByRole('button', { name: 'Continue' }))
    await user.click(await screen.findByRole('button', { name: 'Calculate targets' }))
    await user.click(await screen.findByRole('button', { name: 'Review targets' }))
    await user.click(await screen.findByRole('button', { name: 'Confirm and start' }))

    expect(await screen.findByRole('heading', { name: 'Daily target preview' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Your profile changed. Calculate a new preview before confirming.',
    )
    expect(screen.queryByRole('heading', { name: 'Confirm daily targets' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Review targets' }))
    expect(await screen.findByRole('heading', { name: 'Confirm daily targets' })).toBeInTheDocument()
    expect(onboarding.calculateTargets).toHaveBeenCalledTimes(2)
    expect(onboarding.calculateTargets).toHaveBeenNthCalledWith(1, undefined)
    expect(onboarding.calculateTargets).toHaveBeenNthCalledWith(2, undefined)
  })

  it('restores deterministic values and refreshes automatic preview after manual review', async () => {
    const user = userEvent.setup()
    const refreshedDeterministicPreview: TargetPreview = {
      ...deterministicPreview,
      targets: { calories: 2200, carbs: 295, protein: 128, fat: 58 },
      preview_token: 'e'.repeat(64),
    }
    onboarding.calculateTargets
      .mockResolvedValueOnce(manualPreview)
      .mockResolvedValueOnce(refreshedDeterministicPreview)
    renderOnboarding()

    await user.click(await screen.findByRole('button', { name: 'Continue' }))
    await user.click(await screen.findByRole('button', { name: 'Calculate targets' }))

    const manualToggle = await screen.findByRole('checkbox', { name: 'Set my own daily targets' })
    await user.click(manualToggle)
    fireEvent.change(screen.getByLabelText('Calories (kcal)'), { target: { value: '2400' } })
    await user.click(screen.getByRole('button', { name: 'Review targets' }))
    expect(await screen.findByText('2,400 kcal')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Back' }))
    await user.click(screen.getByRole('checkbox', { name: 'Set my own daily targets' }))
    expect(screen.getByLabelText('Calories (kcal)')).toHaveValue(2172)

    await user.click(screen.getByRole('button', { name: 'Review targets' }))
    expect(await screen.findByText('2,200 kcal')).toBeInTheDocument()
    expect(screen.queryByText('2,400 kcal')).not.toBeInTheDocument()
    expect(onboarding.calculateTargets).toHaveBeenNthCalledWith(1, expect.objectContaining({ calories: 2400 }))
    expect(onboarding.calculateTargets).toHaveBeenNthCalledWith(2, undefined)
  }, ONBOARDING_END_TO_END_TIMEOUT_MS)
})

describe('Auth onboarding destination', () => {
  function renderAuth(from = '/') {
    return render(
      <MemoryRouter initialEntries={[{ pathname: '/login', state: { from } }]}>
        <Routes>
          <Route path="/login" element={<Auth />} />
          <Route path="/onboarding" element={<h1>Onboarding destination</h1>} />
          <Route element={<OnboardingGate />}>
            <Route path="/review" element={<h1>Review destination</h1>} />
            <Route path="/" element={<h1>Home destination</h1>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
  }

  async function submitLogin() {
    fireEvent.click(screen.getByRole('button', { name: 'Login' }))
    fireEvent.change(screen.getByLabelText('Username / email / phone'), { target: { value: 'harry' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password123' } })
    fireEvent.submit(screen.getByLabelText('Password').closest('form')!)
  }

  it('keeps the original destination for a complete login', async () => {
    onboarding.initialSetup = {
      profile,
      goal,
      target: {} as ProfileSetup['target'],
      setup_complete: true,
    }
    renderAuth('/review')
    await submitLogin()

    expect(await screen.findByRole('heading', { name: 'Review destination' })).toBeInTheDocument()
    expect(auth.login).toHaveBeenCalledOnce()
  })

  it('sends an incomplete login and every registration to onboarding', async () => {
    onboarding.initialSetup = {
      profile: null,
      goal: null,
      target: null,
      setup_complete: false,
    }
    const loginView = renderAuth('/review')
    await submitLogin()
    expect(await screen.findByRole('heading', { name: 'Onboarding destination' })).toBeInTheDocument()
    loginView.unmount()

    renderAuth('/review')
    fireEvent.change(screen.getByLabelText('Display name'), { target: { value: 'Harry' } })
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'harry@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'password123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))

    expect(await screen.findByRole('heading', { name: 'Onboarding destination' })).toBeInTheDocument()
  })
})
