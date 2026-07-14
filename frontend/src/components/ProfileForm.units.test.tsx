import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import type { UserProfile } from '../types'
import { ProfileForm } from './ProfileForm'


const profile: UserProfile = {
  height_cm: 175,
  weight_kg: 72,
  age: 24,
  gender: 'male',
  goal: 'maintenance',
  weekly_training_frequency: 3,
  diet_preferences: [],
  allergies_or_restrictions: [],
  target_weight_kg: 70,
  daily_calorie_target: 2200,
  daily_protein_target: 130,
  experience_level: 'novice',
  training_preference: 'mixed',
  target_mode: 'manual',
}

it('converts imperial profile input back to metric before saving', () => {
  let current = profile
  const save = vi.fn()
  const view = render(
    <ProfileForm
      profile={current}
      unitSystem="imperial"
      saving={false}
      onChange={(next) => { current = next; view.rerender(
        <ProfileForm profile={current} unitSystem="imperial" saving={false} onChange={(value) => { current = value }} onSave={save} />
      ) }}
      onSave={save}
    />,
  )

  fireEvent.change(screen.getByLabelText('Weight (lb)'), { target: { value: '176.4' } })
  fireEvent.submit(screen.getByRole('button', { name: 'Save profile' }).closest('form')!)

  expect(save).toHaveBeenCalled()
  expect(save.mock.calls[0][0].weight_kg).toBeCloseTo(80, 1)
})

