import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import { api } from '../services/api'
import { progressApi, type ProgressOverview } from '../services/progressApi'
import { Progress } from './Progress'

vi.mock('../hooks/usePreferences', () => ({
  usePreferences: () => ({ localDate: () => '2026-11-20' }),
}))

vi.mock('../services/progressApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/progressApi')>()
  return {
    ...original,
    progressApi: {
      ...original.progressApi,
      getProgressOverview: vi.fn(),
    },
  }
})

vi.mock('../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/api')>()
  return {
    ...original,
    api: {
      ...original.api,
      listWeeklyReports: vi.fn(),
    },
  }
})

const sampleOverview: ProgressOverview = {
  range_days: 30,
  today: '2026-11-20',
  kpis: {
    latest_weight_kg: 69.6,
    latest_7d_avg_kg: 69.8,
    start_weight_kg: 72.0,
    target_weight_kg: 66.0,
    total_change_kg: -2.4,
    weekly_rate_kg: -0.4,
    distance_to_target_kg: 3.6,
    adherence_mode: 'weekly_frequency',
    adherence_completed: 4,
    adherence_planned: 5,
    adherence_pct: 80,
    calorie_hit_days_7d: 5,
    protein_hit_days_7d: 3,
    logged_meal_days_7d: 6,
    daily_calorie_target: 1850,
    daily_protein_target: 120,
  },
  body_summary: {
    count: 2,
    weight_count: 2,
    start_weight_kg: 72.0,
    latest_weight_kg: 69.6,
    latest_measured_date: '2026-11-20',
    latest_7d_avg_kg: 69.8,
    total_change_kg: -2.4,
    weekly_rate_kg: -0.4,
    target_weight_kg: 66.0,
    distance_to_target_kg: 3.6,
    latest_body_fat_pct: 17.5,
    latest_waist_cm: 81,
    trend: [
      { date: '2026-11-10', weight_kg: 70.0, moving_avg_7d: 70.0, body_fat_pct: 18.0, waist_cm: 82, chest_cm: null, hip_cm: null },
      { date: '2026-11-20', weight_kg: 69.6, moving_avg_7d: 69.8, body_fat_pct: 17.5, waist_cm: 81, chest_cm: null, hip_cm: null },
    ],
  },
  exercises: [
    {
      exercise_key: 'ex-squat',
      catalog_exercise_id: 'ex-squat',
      exercise_name: 'Barbell Squat',
      primary_muscle: 'legs',
      session_count: 3,
      latest_date: '2026-11-18',
      best_weight_kg: 70,
      best_1rm_kg: 85.5,
      best_volume_kg: 2100,
      latest_weight_kg: 70,
      latest_1rm_kg: 85.5,
      delta_1rm_kg: 9.5,
      series: [
        { date: '2026-11-01', session_id: 's1', max_weight_kg: 60, estimated_1rm_kg: 76, total_volume_kg: 1800, total_sets: 4, total_reps: 30, best_set_reps: 8 },
        { date: '2026-11-18', session_id: 's2', max_weight_kg: 70, estimated_1rm_kg: 85.5, total_volume_kg: 2100, total_sets: 4, total_reps: 30, best_set_reps: 8 },
      ],
    },
  ],
  calorie_trend: [{ date: '2026-11-19', value: 1820 }],
  protein_trend: [{ date: '2026-11-19', value: 126 }],
  workout_count_trend: [{ week: '2026-W46', value: 4 }],
  macro_distribution: [{ name: 'protein', value: 126 }],
  training_context: {
    available_equipment: ['barbell', 'dumbbell'],
    weekly_available_days: 4,
    session_duration_min: 50,
    experience_level: 'intermediate',
    preferred_split: 'upper_lower',
    injury_or_limitations: [],
    notes: '',
    updated_at: '2026-11-20T00:00:00Z',
    configured: true,
  },
}

beforeEach(async () => {
  vi.clearAllMocks()
  vi.mocked(api.listWeeklyReports).mockResolvedValue([])
  await i18n.changeLanguage('en-US')
})

describe('Progress dashboard', () => {
  it('renders KPI cards, body trend, and exercise PR table', async () => {
    vi.mocked(progressApi.getProgressOverview).mockResolvedValue(sampleOverview)
    render(
      <MemoryRouter>
        <Progress />
      </MemoryRouter>,
    )
    expect(await screen.findByText('69.6 kg')).toBeInTheDocument()
    expect(screen.getByText(/4 \/ 5/)).toBeInTheDocument()
    expect(screen.getByText(/5 \/ 7 days/)).toBeInTheDocument()
    expect(screen.getByText('Barbell Squat')).toBeInTheDocument()
    expect(screen.getAllByText('85.5 kg').length).toBeGreaterThanOrEqual(1)
  })

  it('renders cold-start guidance when no body or strength logs exist', async () => {
    vi.mocked(progressApi.getProgressOverview).mockResolvedValue({
      ...sampleOverview,
      kpis: {
        ...sampleOverview.kpis,
        latest_weight_kg: null,
        latest_7d_avg_kg: null,
        weekly_rate_kg: null,
      },
      body_summary: { ...sampleOverview.body_summary, count: 0, weight_count: 0, trend: [] },
      exercises: [],
    })
    render(
      <MemoryRouter>
        <Progress />
      </MemoryRouter>,
    )
    expect(await screen.findByText(/No body measurements yet/)).toBeInTheDocument()
    expect(screen.getByText(/No strength exercise records yet/)).toBeInTheDocument()
  })
})
