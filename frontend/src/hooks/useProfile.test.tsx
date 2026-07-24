import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

import { api } from '../services/api'
import type { UserProfile } from '../types'
import { useProfile } from './useProfile'


vi.mock('../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/api')>()
  return {
    ...original,
    api: {
      ...original.api,
      profile: vi.fn(),
      saveTrainingPersonalization: vi.fn(),
    },
  }
})

const profile: UserProfile = {
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

beforeEach(() => {
  vi.mocked(api.profile).mockReset()
  vi.mocked(api.saveTrainingPersonalization).mockReset()
  vi.mocked(api.profile).mockResolvedValue(profile)
})

it('records and rethrows legacy profile save failures', async () => {
  vi.mocked(api.saveTrainingPersonalization).mockRejectedValue(new Error('Legacy save failed'))
  const { result } = renderHook(() => useProfile())
  await waitFor(() => expect(result.current.loading).toBe(false))

  await act(async () => {
    await expect(result.current.save({
      experience_level: profile.experience_level,
      training_preference: profile.training_preference,
    })).rejects.toThrow('Legacy save failed')
  })

  expect(result.current.error).toBe('Legacy save failed')
  expect(result.current.saving).toBe(false)
})
