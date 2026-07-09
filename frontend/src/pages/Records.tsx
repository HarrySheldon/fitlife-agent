import { Bot, CalendarDays, Dumbbell, Utensils } from 'lucide-react'
import type { FormEvent } from 'react'
import { useEffect, useMemo, useState } from 'react'

import { ErrorState } from '../components/ErrorState'
import { FileUploader } from '../components/FileUploader'
import { LoadingState } from '../components/LoadingState'
import { MetricCard } from '../components/MetricCard'
import { api } from '../services/api'
import type { DailyDetail, DailySummary, MealRecord, WorkoutRecord } from '../types'

const emptyMeal: Omit<MealRecord, 'date'> = {
  meal: 'lunch',
  food: '',
  amount: '',
  calories: 0,
  protein: 0,
  carbs: 0,
  fat: 0,
}

const emptyWorkout: Omit<WorkoutRecord, 'date'> = {
  type: 'strength',
  exercise: '',
  muscle_group: '',
  sets: 0,
  reps: 0,
  weight: 0,
  duration_min: 0,
}

export function Records() {
  const [selectedDate, setSelectedDate] = useState(today())
  const [days, setDays] = useState<DailySummary[]>([])
  const [detail, setDetail] = useState<DailyDetail | null>(null)
  const [meal, setMeal] = useState(emptyMeal)
  const [workout, setWorkout] = useState(emptyWorkout)
  const [agentText, setAgentText] = useState('')
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

  async function submitMeal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    await save(async () => {
      const next = await api.addMeal({ date: selectedDate, ...meal })
      setDetail(next)
      setMeal(emptyMeal)
    })
  }

  async function submitWorkout(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    await save(async () => {
      const next = await api.addWorkout({ date: selectedDate, ...workout })
      setDetail(next)
      setWorkout(emptyWorkout)
    })
  }

  async function submitAgentEntry(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    await save(async () => {
      const next = await api.addAgentEntry(selectedDate, agentText)
      setDetail(next.day)
      setAgentText('')
    })
  }

  async function upload(kind: 'meals' | 'workouts', file: File) {
    await save(async () => {
      await api.upload(kind, file)
    })
  }

  async function save(action: () => Promise<void>) {
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

  const summary = detail?.summary

  return (
    <div className="page-stack">
      <header className="page-header inline-header">
        <div>
          <span>Daily records</span>
          <h1>Calendar-based intake and training</h1>
        </div>
        <label className="date-picker">
          <CalendarDays size={18} />
          <input type="date" value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)} />
        </label>
      </header>

      {error ? <ErrorState message={error} /> : null}
      {loading && !detail ? <LoadingState label="Loading records" /> : null}

      {summary ? (
        <div className="metric-grid">
          <MetricCard label="Day calories" value={`${summary.calories} kcal`} detail={selectedDate} />
          <MetricCard label="Day protein" value={`${summary.protein} g`} />
          <MetricCard label="Meals" value={summary.meal_count} />
          <MetricCard label="Training" value={`${summary.training_sessions} sessions`} detail={`${summary.training_duration_min} min`} />
        </div>
      ) : null}

      <div className="calendar-grid">
        {days.map((day) => (
          <button
            key={day.date}
            className={`day-tile ${day.date === selectedDate ? 'active' : ''} ${day.has_data ? 'has-data' : ''}`}
            type="button"
            onClick={() => setSelectedDate(day.date)}
          >
            <span>{day.date.slice(5)}</span>
            <strong>{Math.round(day.calories)}</strong>
            <small>{day.training_sessions} train</small>
          </button>
        ))}
      </div>

      <div className="split-grid">
        <section className="content-panel">
          <h2>Meals</h2>
          <div className="record-list">
            {detail?.meals.map((row, index) => (
              <div className="record-row" key={`${row.date}-${row.meal}-${row.food}-${index}`}>
                <Utensils size={16} />
                <span>{row.meal}</span>
                <strong>{row.food}</strong>
                <small>{row.calories} kcal - {row.protein} g protein</small>
              </div>
            ))}
          </div>
        </section>
        <section className="content-panel">
          <h2>Workouts</h2>
          <div className="record-list">
            {detail?.workouts.map((row, index) => (
              <div className="record-row" key={`${row.date}-${row.exercise}-${index}`}>
                <Dumbbell size={16} />
                <span>{row.type}</span>
                <strong>{row.exercise}</strong>
                <small>{row.duration_min} min - {row.muscle_group}</small>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="record-input-grid">
        <form className="content-panel record-form" onSubmit={(event) => void submitAgentEntry(event)}>
          <h2><Bot size={18} /> Smart entry</h2>
          <textarea required value={agentText} onChange={(event) => setAgentText(event.target.value)} />
          <button className="primary-button" type="submit" disabled={saving}>Parse entry</button>
        </form>

        <form className="content-panel record-form" onSubmit={(event) => void submitMeal(event)}>
          <h2><Utensils size={18} /> Meal form</h2>
          <input required placeholder="Food" value={meal.food} onChange={(event) => setMeal({ ...meal, food: event.target.value })} />
          <input required placeholder="Amount" value={meal.amount} onChange={(event) => setMeal({ ...meal, amount: event.target.value })} />
          <div className="compact-fields">
            <input type="number" min="0" placeholder="Calories" value={meal.calories} onChange={(event) => setMeal({ ...meal, calories: Number(event.target.value) })} />
            <input type="number" min="0" placeholder="Protein" value={meal.protein} onChange={(event) => setMeal({ ...meal, protein: Number(event.target.value) })} />
          </div>
          <button className="primary-button" type="submit" disabled={saving}>Save meal</button>
        </form>

        <form className="content-panel record-form" onSubmit={(event) => void submitWorkout(event)}>
          <h2><Dumbbell size={18} /> Workout form</h2>
          <input required placeholder="Exercise" value={workout.exercise} onChange={(event) => setWorkout({ ...workout, exercise: event.target.value })} />
          <input required placeholder="Muscle group" value={workout.muscle_group} onChange={(event) => setWorkout({ ...workout, muscle_group: event.target.value })} />
          <div className="compact-fields">
            <input type="number" min="0" placeholder="Sets" value={workout.sets} onChange={(event) => setWorkout({ ...workout, sets: Number(event.target.value) })} />
            <input type="number" min="0" placeholder="Minutes" value={workout.duration_min} onChange={(event) => setWorkout({ ...workout, duration_min: Number(event.target.value) })} />
          </div>
          <button className="primary-button" type="submit" disabled={saving}>Save workout</button>
        </form>

        <section className="content-panel record-form">
          <h2>CSV import</h2>
          <FileUploader label="meals.csv" onUpload={(file) => upload('meals', file)} />
          <FileUploader label="workouts.csv" onUpload={(file) => upload('workouts', file)} />
        </section>
      </div>
    </div>
  )
}

function today() {
  return new Date().toISOString().slice(0, 10)
}

function dateRange(endDate: string) {
  const end = new Date(`${endDate}T00:00:00`)
  const start = new Date(end)
  start.setDate(end.getDate() - 29)
  return { start: toDateInput(start), end: toDateInput(end) }
}

function toDateInput(date: Date) {
  return date.toISOString().slice(0, 10)
}
