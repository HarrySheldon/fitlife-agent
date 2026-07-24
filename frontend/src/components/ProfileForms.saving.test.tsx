import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import type { OverallGoalVersion, ProfileVersion } from '../types'
import { OverallGoalForm } from './OverallGoalForm'
import { ProfileDetailsForm } from './ProfileDetailsForm'


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

it('locks every body profile control while saving', async () => {
  const user = userEvent.setup()
  render(
    <ProfileDetailsForm
      profile={profile}
      saving
      onSave={vi.fn()}
    />,
  )

  const controls = [
    screen.getByLabelText('Age'),
    screen.getByLabelText('Height (cm)'),
    screen.getByLabelText('Weight (kg)'),
    screen.getByLabelText('Energy calculation parameter'),
    screen.getByLabelText('Activity level'),
    screen.getByRole('group', { name: 'Safety conditions' }),
    screen.getByLabelText('Disable automatic target calculation'),
  ]
  controls.forEach((control) => expect(control).toBeDisabled())

  await user.type(screen.getByLabelText('Age'), '31')
  await user.selectOptions(screen.getByLabelText('Energy calculation parameter'), 'female')
  await user.click(screen.getByLabelText('Disable automatic target calculation'))
  expect(screen.getByLabelText('Age')).toHaveValue(30)
  expect(screen.getByLabelText('Energy calculation parameter')).toHaveValue('male')
  expect(screen.getByLabelText('Disable automatic target calculation')).not.toBeChecked()
})

it('locks every overall goal radio while saving', async () => {
  const user = userEvent.setup()
  render(<OverallGoalForm goal={goal} saving onSave={vi.fn()} />)

  screen.getAllByRole('radio').forEach((control) => expect(control).toBeDisabled())
  await user.click(screen.getByLabelText('Maintenance'))
  expect(screen.getByLabelText('Fat loss')).toBeChecked()
  expect(screen.getByLabelText('Maintenance')).not.toBeChecked()
})
