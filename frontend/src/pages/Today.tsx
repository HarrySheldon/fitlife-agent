import { Bot, CalendarDays, Dumbbell, Plus, Utensils } from 'lucide-react'
import type { FormEvent } from 'react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { CoachPanel } from '../components/CoachPanel'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { TargetProgress } from '../components/TargetProgress'
import { displayWeight, metricWeight, weightUnit } from '../domain/units'
import { usePreferences } from '../hooks/usePreferences'
import { useToday } from '../hooks/useToday'
import { api } from '../services/api'
import type { MealRecord, WorkoutRecord } from '../types'

type EntryMode = 'smart' | 'meal' | 'workout'

const emptyMeal: Omit<MealRecord, 'date'> = {
  meal: 'lunch', food: '', amount: '', calories: 0, protein: 0, carbs: 0, fat: 0,
}

const emptyWorkout: Omit<WorkoutRecord, 'date'> = {
  type: 'strength', exercise: '', muscle_group: '', sets: 0, reps: 0, weight: 0, duration_min: 0,
}

export function Today() {
  const { t } = useTranslation()
  const { preferences, localDate } = usePreferences()
  const [selectedDate, setSelectedDate] = useState(localDate())
  const [entryMode, setEntryMode] = useState<EntryMode>('smart')
  const [agentText, setAgentText] = useState('')
  const [meal, setMeal] = useState(emptyMeal)
  const [workout, setWorkout] = useState(emptyWorkout)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const { data, loading, error, refresh } = useToday(selectedDate)

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

  async function save(action: () => Promise<unknown>) {
    setSaving(true)
    setSaveError(null)
    try {
      await action()
      await refresh()
    } catch (err) {
      setSaveError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function submitSmart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    await save(async () => {
      await api.addAgentEntry(selectedDate, agentText)
      setAgentText('')
    })
  }

  async function submitMeal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    await save(async () => {
      await api.addMeal({ date: selectedDate, ...meal })
      setMeal(emptyMeal)
    })
  }

  async function submitWorkout(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    await save(async () => {
      await api.addWorkout({ date: selectedDate, ...workout })
      setWorkout(emptyWorkout)
    })
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
          <input type="date" value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)} />
        </label>
      </header>

      {error ? <ErrorState message={error} /> : null}
      {loading && !data ? <LoadingState label={t('today.loading')} /> : null}

      {data ? (
        <div className="today-workspace">
          <div className="today-main">
            <section className="target-grid" aria-label={t('today.targetsLabel')}>
              {data.targets.map((target) => <TargetProgress key={target.label} target={target} />)}
            </section>

            <div className="daily-log-grid">
              <section className="daily-log-section">
                <header><Utensils size={18} /><h2>{t('today.meals')}</h2><span>{data.summary.meal_count}</span></header>
                <div className="record-list">
                  {data.meals.length ? data.meals.map((row, index) => (
                    <div className="record-row" key={`${row.meal}-${row.food}-${index}`}>
                      <Utensils size={16} /><span>{row.meal}</span><strong>{row.food}</strong>
                      <small>{row.calories} kcal · {row.protein} {t('common.proteinUnit')}</small>
                    </div>
                  )) : <EmptyState label={t('today.noMeals')} />}
                </div>
              </section>
              <section className="daily-log-section">
                <header><Dumbbell size={18} /><h2>{t('today.training')}</h2><span>{data.summary.training_sessions}</span></header>
                <div className="record-list">
                  {data.workouts.length ? data.workouts.map((row, index) => (
                    <div className="record-row" key={`${row.exercise}-${index}`}>
                      <Dumbbell size={16} /><span>{row.type}</span><strong>{row.exercise}</strong>
                      <small>{row.duration_min} {t('common.minutesShort')} · {row.muscle_group}{row.weight ? ` · ${displayWeight(row.weight, preferences.unit_system)} ${weightUnit(preferences.unit_system)}` : ''}</small>
                    </div>
                  )) : <EmptyState label={t('today.noTraining')} />}
                </div>
              </section>
            </div>

            <section className="entry-composer">
              <header>
                <div><Plus size={18} /><h2>{t('today.addRecord')}</h2></div>
                <div className="entry-mode" aria-label={t('today.entryMethod')}>
                  <button type="button" className={entryMode === 'smart' ? 'active' : ''} onClick={() => setEntryMode('smart')}><Bot size={16} />{t('today.smart')}</button>
                  <button type="button" className={entryMode === 'meal' ? 'active' : ''} onClick={() => setEntryMode('meal')}><Utensils size={16} />{t('today.meal')}</button>
                  <button type="button" className={entryMode === 'workout' ? 'active' : ''} onClick={() => setEntryMode('workout')}><Dumbbell size={16} />{t('today.training')}</button>
                </div>
              </header>
              {saveError ? <p className="form-error">{saveError}</p> : null}
              {entryMode === 'smart' ? (
                <form className="record-form" onSubmit={(event) => void submitSmart(event)}>
                  <textarea required placeholder={t('today.smartPlaceholder')} value={agentText} onChange={(event) => setAgentText(event.target.value)} />
                  <button className="primary-button" type="submit" disabled={saving}>{t('today.parseAndSave')}</button>
                </form>
              ) : null}
              {entryMode === 'meal' ? (
                <form className="record-form compact-entry-form" onSubmit={(event) => void submitMeal(event)}>
                  <input required placeholder={t('today.food')} value={meal.food} onChange={(event) => setMeal({ ...meal, food: event.target.value })} />
                  <input required placeholder={t('today.amount')} value={meal.amount} onChange={(event) => setMeal({ ...meal, amount: event.target.value })} />
                  <input type="number" min="0" placeholder={t('today.calories')} value={meal.calories} onChange={(event) => setMeal({ ...meal, calories: Number(event.target.value) })} />
                  <input type="number" min="0" placeholder={t('today.protein')} value={meal.protein} onChange={(event) => setMeal({ ...meal, protein: Number(event.target.value) })} />
                  <button className="primary-button" type="submit" disabled={saving}>{t('today.saveMeal')}</button>
                </form>
              ) : null}
              {entryMode === 'workout' ? (
                <form className="record-form compact-entry-form" onSubmit={(event) => void submitWorkout(event)}>
                  <input required placeholder={t('today.exercise')} value={workout.exercise} onChange={(event) => setWorkout({ ...workout, exercise: event.target.value })} />
                  <input required placeholder={t('today.muscleGroup')} value={workout.muscle_group} onChange={(event) => setWorkout({ ...workout, muscle_group: event.target.value })} />
                  <input type="number" min="0" placeholder={t('today.sets')} value={workout.sets} onChange={(event) => setWorkout({ ...workout, sets: Number(event.target.value) })} />
                  <input type="number" min="0" step="0.1" placeholder={t('logbook.weight', { unit: weightUnit(preferences.unit_system) })} value={displayWeight(workout.weight, preferences.unit_system)} onChange={(event) => setWorkout({ ...workout, weight: metricWeight(Number(event.target.value), preferences.unit_system) })} />
                  <input type="number" min="0" placeholder={t('today.minutes')} value={workout.duration_min} onChange={(event) => setWorkout({ ...workout, duration_min: Number(event.target.value) })} />
                  <button className="primary-button" type="submit" disabled={saving}>{t('today.saveTraining')}</button>
                </form>
              ) : null}
            </section>
          </div>
          <CoachPanel surface="today" date={selectedDate} actions={coachActions} />
        </div>
      ) : null}
    </div>
  )
}
