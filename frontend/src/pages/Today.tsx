import {
  CalendarDays,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Dumbbell,
  Flame,
  Lightbulb,
  Plus,
  Scale,
  Sparkles,
  Utensils,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { BodyMeasurementModal } from '../components/BodyMeasurementModal'
import { CoachDrawer } from '../components/CoachDrawer'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { TargetProgress } from '../components/TargetProgress'
import { usePreferences } from '../hooks/usePreferences'
import { useToday } from '../hooks/useToday'
import { useCoach } from '../hooks/useCoach'
import { api } from '../services/api'
import { planCycleApi, type TodayPlanResponse } from '../services/planCycleApi'
import type { DailySummary, NutritionValues, TargetProgress as TargetProgressType } from '../types'

export function Today() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const { localDate } = usePreferences()
  const coach = useCoach()
  const [selectedDate, setSelectedDate] = useState(
    () => validDate(params.get('date')) ?? localDate(),
  )
  const [coachOpen, setCoachOpen] = useState(false)
  const [calendarOpen, setCalendarOpen] = useState(false)
  const [calendarDays, setCalendarDays] = useState<DailySummary[]>([])
  const [calendarLoading, setCalendarLoading] = useState(false)
  const [metricModalOpen, setMetricModalOpen] = useState(false)
  const [quickInput, setQuickInput] = useState('')
  const [todayPlan, setTodayPlan] = useState<TodayPlanResponse | null>(null)
  const [prefilling, setPrefilling] = useState(false)
  const coachTriggerRef = useRef<HTMLButtonElement>(null)
  const { data, loading, error, refreshing, stale } = useToday(selectedDate)

  useEffect(() => {
    let active = true
    planCycleApi
      .getTodayPlan(selectedDate)
      .then((res) => {
        if (active) setTodayPlan(res)
      })
      .catch(() => {
        if (active) setTodayPlan(null)
      })
    return () => {
      active = false
    }
  }, [selectedDate])

  async function handleLogByPlan(dayId: string) {
    setPrefilling(true)
    try {
      const res = await planCycleApi.prefillWorkoutFromDay(dayId)
      navigate(`/today/workout/new?date=${encodeURIComponent(res.log_date)}&draftId=${encodeURIComponent(res.draft_id)}`)
    } finally {
      setPrefilling(false)
    }
  }

  useEffect(() => {
    if (!calendarOpen) return
    let active = true
    setCalendarLoading(true)
    const end = new Date(`${localDate()}T00:00:00`)
    const start = new Date(end)
    start.setDate(end.getDate() - 29)
    api
      .calendarDays(start.toISOString().slice(0, 10), end.toISOString().slice(0, 10))
      .then((items) => {
        if (active) setCalendarDays(items)
      })
      .catch(() => {
        // Keep empty strip if unavailable
      })
      .finally(() => {
        if (active) setCalendarLoading(false)
      })
    return () => {
      active = false
    }
  }, [calendarOpen, localDate])

  function handleQuickSmartEntry(event: FormEvent) {
    event.preventDefault()
    const trimmed = quickInput.trim()
    const qs = new URLSearchParams({ date: selectedDate })
    if (trimmed) qs.set('text', trimmed)
    navigate(`/today/smart-entry?${qs.toString()}`)
  }

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

  return (
    <div className="page-stack today-page">
      <header className="page-header inline-header">
        <div>
          <span>{t('today.eyebrow')}</span>
          <h1>{t('today.title')}</h1>
        </div>
        <div className="today-date-controls">
          <label className="date-picker">
            <CalendarDays size={18} />
            <input
              aria-label={t('today.date')}
              type="date"
              value={selectedDate}
              onChange={(event) => setSelectedDate(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="secondary-button"
            aria-expanded={calendarOpen}
            onClick={() => setCalendarOpen((open) => !open)}
          >
            {calendarOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            {t('today.historyCalendar')}
          </button>
        </div>
      </header>

      {calendarOpen ? (
        <section className="today-calendar-drawer" aria-label={t('logbook.lastDays')}>
          {calendarLoading ? <LoadingState label={t('logbook.loading')} /> : (
            <div className="calendar-strip">
              {calendarDays.map((day) => (
                <button
                  key={day.date}
                  type="button"
                  className={`day-tile ${day.has_data ? 'has-data' : ''} ${day.date === selectedDate ? 'selected' : ''}`}
                  onClick={() => {
                    setSelectedDate(day.date)
                    setCalendarOpen(false)
                  }}
                >
                  <span>{day.date.slice(5)}</span>
                  <strong>{Math.round(day.calories)}</strong>
                  <small>{day.training_sessions} {t('common.trainingShort')}</small>
                </button>
              ))}
            </div>
          )}
        </section>
      ) : null}

      {error ? <ErrorState message={error} /> : null}
      {loading && !data ? <LoadingState label={t('today.loading')} /> : null}
      {refreshing ? <p role="status">{t('today.refreshing')}</p> : null}
      {stale ? <p role="status">{t('today.staleData')}</p> : null}

      {data ? (
        <div className="today-workspace">
          <div className="today-main">
            {todayPlan?.day ? (
              <section className="panel-card today-plan-card" aria-labelledby="today-plan-heading">
                <header className="section-card-header inline-between">
                  <div>
                    <span className="eyebrow-tag">{todayPlan.cycle?.title ?? t('planCycle.todayPlan')}</span>
                    <h2 id="today-plan-heading">
                      {todayPlan.day.focus || t('planCycle.todayPlan')}
                      {todayPlan.day.estimated_duration_min
                        ? ` · ${todayPlan.day.estimated_duration_min} ${t('common.minutesShort')}`
                        : ''}
                    </h2>
                  </div>
                  <div className="today-plan-actions">
                    <span className={`adherence-pill ${todayPlan.day.adherence ?? 'upcoming'}`}>
                      {todayPlan.day.adherence === 'completed' ? <CheckCircle2 size={14} /> : null}
                      {t(`planCycle.status.${todayPlan.day.adherence ?? 'upcoming'}`)}
                    </span>
                    {todayPlan.day.day_type !== 'rest' ? (
                      <button
                        type="button"
                        className="primary-button"
                        disabled={prefilling}
                        onClick={() => void handleLogByPlan(todayPlan.day!.id)}
                      >
                        <Dumbbell size={15} />
                        {prefilling ? t('common.working') : t('planCycle.logByPlan')}
                      </button>
                    ) : null}
                    <Link className="secondary-button" to="/plan">
                      {t('planCycle.adjustInPlan')}
                    </Link>
                  </div>
                </header>
                {todayPlan.day.prescribed_exercises.length ? (
                  <ul className="prescribed-list">
                    {todayPlan.day.prescribed_exercises.map((ex, idx) => (
                      <li key={`${ex.catalog_exercise_id ?? ex.name}-${idx}`}>
                        <strong>{ex.name}</strong>
                        <span>
                          {ex.exercise_type === 'cardio'
                            ? `${ex.duration_min ?? 30} ${t('common.minutesShort')}`
                            : `${ex.sets} × ${ex.reps}${ex.target_weight_kg != null ? ` @ ${ex.target_weight_kg} kg` : ''}`}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted-copy">{todayPlan.day.notes || t('planCycle.restDayCopy')}</p>
                )}
              </section>
            ) : null}

            <section className="target-grid nutrition-target-grid" aria-label={t('today.targetsLabel')}>
              {progress.map((target) => <TargetProgress key={target.label} target={target} />)}
            </section>

            <section className="today-record-actions" aria-labelledby="today-add-record">
              <div>
                <span>{t('today.recordEyebrow')}</span>
                <h2 id="today-add-record">{t('today.addRecord')}</h2>
              </div>
              <div>
                <div className="planned-meal-count">
                  <span>{t('today.plannedMeals')}</span>
                  <strong>{data.planned_meal_count}</strong>
                </div>
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
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => navigate(`/today/smart-entry?date=${encodeURIComponent(selectedDate)}`)}
                >
                  <Sparkles size={17} />
                  {t('today.smartEntry')}
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setMetricModalOpen(true)}
                >
                  <Scale size={17} />
                  {t('bodyMetrics.logShort')}
                </button>
              </div>
            </section>

            <form className="today-quick-entry-bar" onSubmit={handleQuickSmartEntry}>
              <input
                type="text"
                aria-label={t('today.quickInputLabel')}
                placeholder={t('today.quickInputPlaceholder')}
                value={quickInput}
                onChange={(e) => setQuickInput(e.target.value)}
              />
              <button type="submit" className="secondary-button">
                <Sparkles size={15} />
                {t('today.quickInputSubmit')}
              </button>
            </form>
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

            {buildTodayHint(data, todayPlan, t) ? (
              <section className="today-hint-bar" aria-label={t('today.hintLabel')}>
                <Lightbulb size={17} />
                <span>{buildTodayHint(data, todayPlan, t)}</span>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() =>
                    navigate(
                      `/coach?${new URLSearchParams({
                        surface: 'today',
                        date: selectedDate,
                        prompt: buildTodayHint(data, todayPlan, t) ?? t('today.explain'),
                      }).toString()}`,
                    )
                  }
                >
                  <Bot size={15} />
                  {t('today.askCoach')}
                </button>
              </section>
            ) : null}
          </div>
          {coach ? <div className="coach-actions">{coachActions.map(item => <button key={item.action} type="button" disabled={coach.sending || coach.active !== null} onClick={() => void coach.send({ question: `${item.label} · ${selectedDate}`, action: item.action, surface: 'today', date: selectedDate })}>{item.label}</button>)}</div> : <button ref={coachTriggerRef} className="secondary-button coach-trigger" type="button" onClick={() => setCoachOpen(true)}>
            <Bot size={17} />{t('coach.open')}
          </button>}
          {!coach ? <CoachDrawer open={coachOpen} onClose={() => setCoachOpen(false)} returnFocusRef={coachTriggerRef} surface="today" date={selectedDate} actions={coachActions} /> : null}
        </div>
      ) : null}

      <BodyMeasurementModal
        open={metricModalOpen}
        defaultDate={selectedDate}
        onClose={() => setMetricModalOpen(false)}
      />
    </div>
  )
}

function validDate(value: string | null): string | null {
  return value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null
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

function buildTodayHint(
  data: { consumed: NutritionValues; target: NutritionValues | null },
  todayPlan: TodayPlanResponse | null,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string | null {
  const proteinGap = (data.target?.protein ?? 0) - data.consumed.protein
  if (proteinGap >= 25) {
    return t('today.hintProteinGap', { grams: Math.round(proteinGap) })
  }
  if (todayPlan?.day && todayPlan.day.day_type !== 'rest' && todayPlan.day.adherence === 'upcoming') {
    return t('today.hintPlanPending', { focus: todayPlan.day.focus })
  }
  return null
}
