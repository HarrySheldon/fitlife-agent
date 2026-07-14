import { CalendarDays, Dumbbell, Utensils } from 'lucide-react'
import type { FormEvent } from 'react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { FileUploader } from '../components/FileUploader'
import { LoadingState } from '../components/LoadingState'
import { displayWeight, metricWeight, weightUnit } from '../domain/units'
import { usePreferences } from '../hooks/usePreferences'
import { api } from '../services/api'
import type { DailyDetail, DailySummary, MealRecord, WorkoutRecord } from '../types'

const emptyMeal: Omit<MealRecord, 'date'> = {
  meal: 'lunch', food: '', amount: '', calories: 0, protein: 0, carbs: 0, fat: 0,
}

const emptyWorkout: Omit<WorkoutRecord, 'date'> = {
  type: 'strength', exercise: '', muscle_group: '', sets: 0, reps: 0, weight: 0, duration_min: 0,
}

export function Logbook() {
  const { t } = useTranslation()
  const { preferences, localDate } = usePreferences()
  const [selectedDate, setSelectedDate] = useState(localDate())
  const [days, setDays] = useState<DailySummary[]>([])
  const [detail, setDetail] = useState<DailyDetail | null>(null)
  const [meal, setMeal] = useState(emptyMeal)
  const [workout, setWorkout] = useState(emptyWorkout)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const range = useMemo(() => dateRange(selectedDate), [selectedDate])

  useEffect(() => {
    void refresh()
  }, [selectedDate])

  async function refresh() {
    setLoading(true)
    setError(null)
    try {
      const [nextDays, nextDetail] = await Promise.all([
        api.calendarDays(range.start, range.end),
        api.calendarDay(selectedDate),
      ])
      setDays(nextDays)
      setDetail(nextDetail)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  async function save(action: () => Promise<unknown>) {
    setSaving(true)
    setError(null)
    try {
      await action()
      await refresh()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
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

  async function upload(kind: 'meals' | 'workouts', file: File) {
    await save(() => api.upload(kind, file))
  }

  return (
    <div className="page-stack logbook-page">
      <header className="page-header inline-header">
        <div><span>{t('logbook.eyebrow')}</span><h1>{t('logbook.title')}</h1></div>
        <label className="date-picker"><CalendarDays size={18} /><input type="date" value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)} /></label>
      </header>

      {error ? <ErrorState message={error} /> : null}
      {loading && !detail ? <LoadingState label={t('logbook.loading')} /> : null}

      <section className="calendar-strip" aria-label={t('logbook.lastDays')}>
        {days.map((day) => (
          <button key={day.date} className={`day-tile ${day.date === selectedDate ? 'active' : ''} ${day.has_data ? 'has-data' : ''}`} type="button" onClick={() => setSelectedDate(day.date)}>
            <span>{day.date.slice(5)}</span><strong>{Math.round(day.calories)}</strong><small>{day.training_sessions} {t('common.trainingShort')}</small>
          </button>
        ))}
      </section>

      <div className="daily-log-grid">
        <section className="daily-log-section">
          <header><Utensils size={18} /><h2>{t('logbook.meals')}</h2><span>{detail?.meals.length ?? 0}</span></header>
          <div className="record-list">
            {detail?.meals.length ? detail.meals.map((row, index) => (
              <div className="record-row" key={`${row.meal}-${row.food}-${index}`}><Utensils size={16} /><span>{row.meal}</span><strong>{row.food}</strong><small>{row.calories} kcal · {row.protein} {t('common.proteinUnit')}</small></div>
            )) : <EmptyState label={t('logbook.noMeals')} />}
          </div>
        </section>
        <section className="daily-log-section">
          <header><Dumbbell size={18} /><h2>{t('logbook.training')}</h2><span>{detail?.workouts.length ?? 0}</span></header>
          <div className="record-list">
            {detail?.workouts.length ? detail.workouts.map((row, index) => (
              <div className="record-row" key={`${row.exercise}-${index}`}><Dumbbell size={16} /><span>{row.type}</span><strong>{row.exercise}</strong><small>{row.duration_min} {t('common.minutesShort')} · {row.muscle_group}{row.weight ? ` · ${displayWeight(row.weight, preferences.unit_system)} ${weightUnit(preferences.unit_system)}` : ''}</small></div>
            )) : <EmptyState label={t('logbook.noTraining')} />}
          </div>
        </section>
      </div>

      <div className="logbook-tools">
        <form className="entry-composer record-form" onSubmit={(event) => void submitMeal(event)}>
          <h2><Utensils size={18} /> {t('logbook.addMeal', { date: selectedDate })}</h2>
          <div className="compact-entry-form">
            <input required placeholder={t('logbook.food')} value={meal.food} onChange={(event) => setMeal({ ...meal, food: event.target.value })} />
            <input required placeholder={t('logbook.amount')} value={meal.amount} onChange={(event) => setMeal({ ...meal, amount: event.target.value })} />
            <input type="number" min="0" placeholder={t('logbook.calories')} value={meal.calories} onChange={(event) => setMeal({ ...meal, calories: Number(event.target.value) })} />
            <input type="number" min="0" placeholder={t('logbook.protein')} value={meal.protein} onChange={(event) => setMeal({ ...meal, protein: Number(event.target.value) })} />
            <button className="primary-button" type="submit" disabled={saving}>{t('common.save')}</button>
          </div>
        </form>
        <form className="entry-composer record-form" onSubmit={(event) => void submitWorkout(event)}>
          <h2><Dumbbell size={18} /> {t('logbook.addTraining', { date: selectedDate })}</h2>
          <div className="compact-entry-form">
            <input required placeholder={t('logbook.exercise')} value={workout.exercise} onChange={(event) => setWorkout({ ...workout, exercise: event.target.value })} />
            <input required placeholder={t('logbook.muscleGroup')} value={workout.muscle_group} onChange={(event) => setWorkout({ ...workout, muscle_group: event.target.value })} />
            <input type="number" min="0" placeholder={t('logbook.sets')} value={workout.sets} onChange={(event) => setWorkout({ ...workout, sets: Number(event.target.value) })} />
            <input type="number" min="0" step="0.1" placeholder={t('logbook.weight', { unit: weightUnit(preferences.unit_system) })} value={displayWeight(workout.weight, preferences.unit_system)} onChange={(event) => setWorkout({ ...workout, weight: metricWeight(Number(event.target.value), preferences.unit_system) })} />
            <input type="number" min="0" placeholder={t('logbook.minutes')} value={workout.duration_min} onChange={(event) => setWorkout({ ...workout, duration_min: Number(event.target.value) })} />
            <button className="primary-button" type="submit" disabled={saving}>{t('common.save')}</button>
          </div>
        </form>
        <section className="import-tool">
          <div><span>{t('logbook.optionalInput')}</span><h2>{t('logbook.csvImport')}</h2></div>
          <FileUploader label="meals.csv" onUpload={(file) => upload('meals', file)} />
          <FileUploader label="workouts.csv" onUpload={(file) => upload('workouts', file)} />
        </section>
      </div>
    </div>
  )
}

function dateRange(endDate: string) {
  const end = new Date(`${endDate}T00:00:00`)
  const start = new Date(end)
  start.setDate(end.getDate() - 29)
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) }
}
