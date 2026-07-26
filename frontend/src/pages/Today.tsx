import {
  CalendarDays,
  Dumbbell,
  Flame,
  Plus,
  Utensils,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { CoachPanel } from '../components/CoachPanel'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { TargetProgress } from '../components/TargetProgress'
import { usePreferences } from '../hooks/usePreferences'
import { useToday } from '../hooks/useToday'
import { api } from '../services/api'
import type { NutritionValues, TargetProgress as TargetProgressType } from '../types'

export function Today() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { localDate } = usePreferences()
  const [selectedDate, setSelectedDate] = useState(localDate())
  const { data, loading, error, refresh } = useToday(selectedDate)
  const [updatingMealCount, setUpdatingMealCount] = useState(false)
  const [mealCountError, setMealCountError] = useState<string | null>(null)

  const coachActions = useMemo(() => {
    const labels = {
      explain_today: t('today.explain'),
      suggest_next_meal: t('today.suggestMeal'),
      adjust_today_training: t('today.adjustTraining'),
    } as const
    return (data?.coach_actions ?? [])
      .filter((action): action is keyof typeof labels => action in labels)
      .map((action) => ({ action, label: labels[action] }))
  }, [data?.coach_actions, t])

  const progress = data
    ? nutritionProgress(data.consumed, data.target, t)
    : []

  async function setPlannedMealCount(value: number) {
    setUpdatingMealCount(true)
    setMealCountError(null)
    try {
      await api.setPlannedMealCount(selectedDate, value)
      await refresh()
    } catch (cause) {
      setMealCountError((cause as Error).message)
    } finally {
      setUpdatingMealCount(false)
    }
  }

  return (
    <div className="page-stack today-page">
      <header className="page-header inline-header">
        <div>
          <span>{t('today.eyebrow')}</span>
          <h1>{t('today.title')}</h1>
        </div>
        <label className="date-picker">
          <CalendarDays size={18} />
          <input
            aria-label={t('today.date')}
            type="date"
            value={selectedDate}
            onChange={(event) => setSelectedDate(event.target.value)}
          />
        </label>
      </header>

      {error ? <ErrorState message={error} /> : null}
      {loading && !data ? <LoadingState label={t('today.loading')} /> : null}

      {data ? (
        <div className="today-workspace">
          <div className="today-main">
            <section className="target-grid nutrition-target-grid" aria-label={t('today.targetsLabel')}>
              {progress.map((target) => <TargetProgress key={target.label} target={target} />)}
            </section>

            <section className="today-record-actions" aria-labelledby="today-add-record">
              <div>
                <span>{t('today.recordEyebrow')}</span>
                <h2 id="today-add-record">{t('today.addRecord')}</h2>
              </div>
              <div>
                <label className="planned-meal-count">
                  <span>{t('today.plannedMeals')}</span>
                  <select
                    aria-label={t('today.plannedMeals')}
                    value={data.planned_meal_count}
                    disabled={updatingMealCount}
                    onChange={(event) => void setPlannedMealCount(Number(event.target.value))}
                  >
                    {Array.from({ length: 12 }, (_, index) => index + 1).map((count) => (
                      <option key={count} value={count}>{count}</option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => navigate(`/today/meal/new?date=${encodeURIComponent(selectedDate)}`)}
                >
                  <Utensils size={17} />
                  {t('today.addMeal')}
                </button>
                <button
                  type="button"
                  className="primary-button"
                  onClick={() => navigate(`/today/workout/new?date=${encodeURIComponent(selectedDate)}`)}
                >
                  <Plus size={17} />
                  {t('today.addTraining')}
                </button>
              </div>
            </section>
            {mealCountError ? <p className="form-error">{mealCountError}</p> : null}

            {data.meals?.length ? (
              <section className="daily-log-section">
                <header>
                  <Utensils size={18} />
                  <h2>{t('today.meals')}</h2>
                  <span>{t('today.mealCount', {
                    recorded: data.recorded_meal_count,
                    planned: data.planned_meal_count,
                  })}</span>
                </header>
                <div className="record-list">
                  {data.meals.map((meal) => (
                    <div className="record-row today-meal-row" key={meal.id}>
                      <Utensils size={16} />
                      <span>{t(`mealEntry.types.${meal.meal_type}`, {
                        defaultValue: meal.meal_type,
                      })}</span>
                      <strong>{meal.name}</strong>
                      <small>
                        {Math.round(meal.nutrition.calories)} kcal
                        {' · '}
                        {Math.round(meal.nutrition.protein)} {t('common.proteinUnit')}
                        {' · '}
                        {t('today.itemCount', { count: meal.item_count })}
                      </small>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}

            {data.workouts?.length ? (
              <section className="daily-log-section">
                <header>
                  <Dumbbell size={18} />
                  <h2>{t('today.training')}</h2>
                  <span>{data.workouts.length}</span>
                </header>
                <div className="record-list">
                  {data.workouts.map((workout) => (
                    <div className="record-row today-workout-row" key={workout.id}>
                      <Dumbbell size={16} />
                      <span>{workout.intensity
                        ? t(`workoutEntry.intensities.${workout.intensity}`, {
                          defaultValue: workout.intensity,
                        })
                        : t('today.training')}</span>
                      <strong>{workout.title}</strong>
                      <small>
                        {workout.duration_min != null
                          ? `${Math.round(workout.duration_min)} ${t('common.minutesShort')} · `
                          : ''}
                        {workout.calories != null ? (
                          <>
                            <Flame size={13} />
                            {Math.round(workout.calories)} kcal
                            {workout.contains_estimates
                              ? ` · ${t('today.containsEstimates')}`
                              : ''}
                          </>
                        ) : t('today.noCalorieEstimate')}
                      </small>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}
          </div>
          <CoachPanel surface="today" date={selectedDate} actions={coachActions} />
        </div>
      ) : null}
    </div>
  )
}

function nutritionProgress(
  consumed: NutritionValues,
  target: NutritionValues | null,
  t: (key: string) => string,
): TargetProgressType[] {
  return ([
    ['calories', 'kcal'],
    ['carbs', 'g'],
    ['protein', 'g'],
    ['fat', 'g'],
  ] as const).map(([key, unit]) => {
    const current = consumed[key]
    const goal = target?.[key] ?? 0
    const remaining = goal - current
    return {
      label: t(`today.nutrients.${key}`),
      current,
      target: goal,
      unit,
      remaining,
      status: goal > 0 && current > goal ? 'over' : goal > 0 && current >= goal ? 'met' : 'under',
    }
  })
}
