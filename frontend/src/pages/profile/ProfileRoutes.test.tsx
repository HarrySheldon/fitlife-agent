import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../../i18n'
import type { ProfileSetup, UserProfile } from '../../types'
import { Profile } from '../Profile'
import { EditProfile } from './EditProfile'

const setup: ProfileSetup = {
  setup_complete: true,
  profile: {
    id: 'profile-1', user_id: 'user-1', age: 30, height_cm: 175, weight_kg: 70,
    energy_parameter: 'male', activity_level: 'moderate', auto_target_disabled: false,
    safety_conditions: [], effective_from: '2026-08-26T00:00:00Z', created_at: '2026-08-26T00:00:00Z',
  },
  goal: { id: 'goal-1', user_id: 'user-1', goal: 'maintenance', effective_from: '2026-08-26T00:00:00Z', created_at: '2026-08-26T00:00:00Z' },
  target: { id: 'target-1', user_id: 'user-1', profile_version_id: 'profile-1', overall_goal_version_id: 'goal-1', calories: 2200, carbs: 250, protein: 140, fat: 70, source: 'manual', formula_version: null, rationale: {}, effective_from: '2026-08-26T00:00:00Z', created_at: '2026-08-26T00:00:00Z' },
}

const legacyProfile: UserProfile = {
  height_cm: 175, weight_kg: 70, age: 30, gender: 'male', goal: 'maintenance',
  weekly_training_frequency: 4, diet_preferences: [], allergies_or_restrictions: [],
  target_weight_kg: 70, daily_calorie_target: 2200, daily_protein_target: 140,
  experience_level: 'experienced', training_preference: 'mixed', target_mode: 'manual',
}

vi.mock('../../hooks/usePreferences', () => ({
  usePreferences: () => ({ preferences: { unit_system: 'imperial' } }),
}))
vi.mock('../../hooks/useProfileSetup', () => ({
  useProfileSetup: () => ({ setup, preview: null, restriction: null, loading: false, saving: false, calculating: false, confirming: false, stalePreview: false, error: null, updateProfile: vi.fn(), updateOverallGoal: vi.fn(), calculateTargets: vi.fn(), confirmTargets: vi.fn() }),
}))
vi.mock('../../hooks/useProfile', () => ({
  useProfile: () => ({ profile: legacyProfile, loading: false, saving: false, error: null, save: vi.fn() }),
}))
vi.mock('../../services/api', () => ({ api: { targetHistory: vi.fn().mockResolvedValue([]) } }))

function renderRoute(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><Routes>
    <Route path="/profile" element={<Profile />} />
    <Route path="/profile/edit" element={<EditProfile />} />
  </Routes></MemoryRouter>)
}

describe('profile task routes', () => {
  beforeEach(async () => { await i18n.changeLanguage('en-US') })

  it('keeps /profile read-only with an imperial-aware summary and edit action', async () => {
    renderRoute('/profile')
    expect(await screen.findByText(/5 ft 9 in/i)).toBeInTheDocument()
    expect(screen.getByText(/154\.3 lb/i)).toBeInTheDocument()
    expect(screen.getByText(/2200 kcal/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /edit profile/i })).toHaveAttribute('href', '/profile/edit')
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument()
  })

  it('owns profile form controls only on /profile/edit', async () => {
    renderRoute('/profile/edit')
    expect(await screen.findByLabelText('Age')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save body profile' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /back to profile/i })).toHaveAttribute('href', '/profile')
  })
})
