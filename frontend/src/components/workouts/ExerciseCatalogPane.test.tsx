import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../../i18n'
import { workoutApi } from '../../services/workoutApi'
import type { ExerciseCatalogItem } from '../../types/workouts'
import { ExerciseCatalogPane } from './ExerciseCatalogPane'

vi.mock('../../services/workoutApi', () => ({
  workoutApi: {
    searchExercises: vi.fn(),
    setFavorite: vi.fn(),
    createCustomExercise: vi.fn(),
  },
}))

const squat: ExerciseCatalogItem = {
  id: 'exercise-free-exercise-db-Barbell_Full_Squat',
  owner_user_id: null,
  source: 'public',
  source_name: 'free-exercise-db',
  source_record_id: 'Barbell_Full_Squat',
  dataset_version: '2026-08-09',
  name: '杠铃深蹲',
  exercise_type: 'strength',
  primary_muscle: '股四头肌',
  secondary_muscles: ['小腿肌群', '臀肌', '腘绳肌', '下背部肌群'],
  met: null,
  license: 'Unlicense',
  attribution: 'free-exercise-db contributors',
  provenance: {},
  content_hash: 'squat-hash',
  active: true,
  aliases: ['Barbell Full Squat', '深蹲'],
  is_favorite: false,
  use_count: 0,
  last_used_at: null,
  rank_group: 3,
}

beforeEach(async () => {
  vi.clearAllMocks()
  await i18n.changeLanguage('en-US')
  vi.mocked(workoutApi.searchExercises).mockResolvedValue([squat])
})

describe('ExerciseCatalogPane', () => {
  it('renders the Mainland exercise and muscle names returned by the service', async () => {
    render(
      <ExerciseCatalogPane
        selectedCatalogIds={[]}
        onAddExercise={vi.fn()}
      />,
    )

    fireEvent.change(screen.getByLabelText('Search exercises'), {
      target: { value: 'Barbell Full Squat' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('杠铃深蹲')).toBeInTheDocument()
    expect(screen.getByText('股四头肌')).toBeInTheDocument()
    expect(workoutApi.searchExercises).toHaveBeenCalledWith('Barbell Full Squat')
  })
})
