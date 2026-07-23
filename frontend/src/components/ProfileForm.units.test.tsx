import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { ProfileVersion } from '../types'
import { ProfileDetailsForm } from './ProfileDetailsForm'


const profile: ProfileVersion = {
  id: 'profile-1',
  user_id: 'user-1',
  height_cm: 175,
  weight_kg: 72,
  age: 24,
  energy_parameter: 'male',
  activity_level: 'moderate',
  auto_target_disabled: false,
  safety_conditions: [],
  effective_from: '2026-07-23T08:00:00Z',
  created_at: '2026-07-23T08:00:00Z',
}

it('converts imperial profile input back to metric before saving', () => {
  const save = vi.fn()
  render(
    <ProfileDetailsForm
      profile={profile}
      unitSystem="imperial"
      saving={false}
      onSave={save}
    />,
  )

  fireEvent.change(screen.getByLabelText('Weight (lb)'), { target: { value: '176.4' } })
  fireEvent.change(screen.getByLabelText('Height (ft)'), { target: { value: '6' } })
  fireEvent.change(screen.getByLabelText('Height (in)'), { target: { value: '0' } })
  fireEvent.submit(screen.getByRole('button', { name: 'Save body profile' }).closest('form')!)

  expect(save).toHaveBeenCalled()
  expect(save.mock.calls[0][0].weight_kg).toBeCloseTo(80, 1)
  expect(save.mock.calls[0][0].height_cm).toBeCloseTo(182.9, 1)
})

it('derives imperial weight limits from the backend kilogram bounds', () => {
  render(
    <ProfileDetailsForm
      profile={profile}
      unitSystem="imperial"
      saving={false}
      onSave={vi.fn()}
    />,
  )

  expect(screen.getByLabelText('Weight (lb)')).toHaveAttribute('min', '66.2')
  expect(screen.getByLabelText('Weight (lb)')).toHaveAttribute('max', '661.3')
})

describe.each([
  { feet: 3, inches: 11 },
  { feet: 7, inches: 7 },
])('imperial combined height validation', ({ feet, inches }) => {
  it(`rejects ${feet} ft ${inches} in before calling the API`, () => {
    const save = vi.fn()
    render(
      <ProfileDetailsForm
        profile={profile}
        unitSystem="imperial"
        saving={false}
        onSave={save}
      />,
    )

    fireEvent.change(screen.getByLabelText('Height (ft)'), { target: { value: String(feet) } })
    fireEvent.change(screen.getByLabelText('Height (in)'), { target: { value: String(inches) } })
    fireEvent.submit(screen.getByRole('button', { name: 'Save body profile' }).closest('form')!)

    expect(save).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Imperial height must convert to between 120 and 230 cm.',
    )
  })
})

