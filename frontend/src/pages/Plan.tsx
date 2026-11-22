import {
  Bot,
  CalendarRange,
  Check,
  CheckCircle2,
  Dumbbell,
  Plus,
  SkipForward,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { WeeklyAutomationBanner } from '../components/WeeklyAutomationBanner'
import { api } from '../services/api'
import {
  planCycleApi,
  type ActivePlanCycleResponse,
  type CycleGoalType,
  type PlanDay,
} from '../services/planCycleApi'
import type { StoredPlan } from '../types'

const WEEKDAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

export function Plan() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [cycleState, setCycleState] = useState<ActivePlanCycleResponse | null>(null)
  const [selectedWeek, setSelectedWeek] = useState<number | undefined>(undefined)
  const [selectedDayId, setSelectedDayId] = useState<string | null>(null)
  const [cycleLoading, setCycleLoading] = useState(true)
  const [cycleError, setCycleError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [newDuration, setNewDuration] = useState<number>(8)
  const [newGoal, setNewGoal] = useState<CycleGoalType>('fat_loss')
  const [newTitle, setNewTitle] = useState('')
  const [busyAction, setBusyAction] = useState<string | null>(null)

  const [plans, setPlans] = useState<StoredPlan[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadCycle = useCallback((weekIndex?: number) => {
    let active = true
    setCycleLoading(true)
    setCycleError(null)
    planCycleApi
      .getActiveCycle(weekIndex)
      .then((res) => {
        if (!active) return
        setCycleState(res)
        if (res.current_week) setSelectedWeek(res.current_week)
        if (res.days.length) {
          setSelectedDayId((prev) =>
            res.days.some((d) => d.id === prev) ? prev : res.days[0].id,
          )
        }
      })
      .catch((cause) => {
        if (active) setCycleError(cause instanceof Error ? cause.message : t('plan.loadingHistory'))
      })
      .finally(() => {
        if (active) setCycleLoading(false)
      })
    return () => {
      active = false
    }
  }, [t])

  useEffect(() => loadCycle(selectedWeek), [loadCycle, selectedWeek])

  useEffect(() => {
    let active = true
    api
      .listPlans()
      .then((items) => {
        if (active) setPlans(items)
      })
      .catch((err) => {
        if (active) setError((err as Error).message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  const selectedDay: PlanDay | null = useMemo(() => {
    if (!cycleState?.days.length) return null
    return cycleState.days.find((d) => d.id === selectedDayId) ?? cycleState.days[0]
  }, [cycleState?.days, selectedDayId])

  async function handleCreateDraft(event: FormEvent) {
    event.preventDefault()
    setCreating(true)
    setCycleError(null)
    try {
      await planCycleApi.createCycleDraft({
        title: newTitle.trim() || undefined,
        goal_type: newGoal,
        duration_weeks: newDuration,
      })
      setNewTitle('')
      setShowCreateForm(false)
      loadCycle(selectedWeek)
    } catch (cause) {
      setCycleError(cause instanceof Error ? cause.message : t('planCycle.createFailed'))
    } finally {
      setCreating(false)
    }
  }

  async function handleActivate(cycleId: string) {
    setBusyAction(`activate:${cycleId}`)
    try {
      await planCycleApi.activateCycle(cycleId)
      setSelectedWeek(1)
      loadCycle(1)
    } catch (cause) {
      setCycleError(cause instanceof Error ? cause.message : t('planCycle.activateFailed'))
    } finally {
      setBusyAction(null)
    }
  }

  async function handleDiscard(cycleId: string) {
    setBusyAction(`discard:${cycleId}`)
    try {
      await planCycleApi.discardDraft(cycleId)
      loadCycle(selectedWeek)
    } catch (cause) {
      setCycleError(cause instanceof Error ? cause.message : t('planCycle.discardFailed'))
    } finally {
      setBusyAction(null)
    }
  }

  async function handleToggleSkip(day: PlanDay) {
    setBusyAction(`skip:${day.id}`)
    try {
      await planCycleApi.updateDay(
        day.id,
        day.status_override === 'skipped'
          ? { clear_status_override: true }
          : { status_override: 'skipped' },
      )
      loadCycle(selectedWeek)
    } catch (cause) {
      setCycleError(cause instanceof Error ? cause.message : t('planCycle.updateFailed'))
    } finally {
      setBusyAction(null)
    }
  }

  async function handlePrefillWorkout(dayId: string) {
    setBusyAction(`prefill:${dayId}`)
    try {
      const res = await planCycleApi.prefillWorkoutFromDay(dayId)
      navigate(`/today/workout/new?date=${encodeURIComponent(res.log_date)}&draftId=${encodeURIComponent(res.draft_id)}`)
    } catch (cause) {
      setCycleError(cause instanceof Error ? cause.message : t('planCycle.prefillFailed'))
    } finally {
      setBusyAction(null)
    }
  }

  const activeCycle = cycleState?.active ?? null
  const drafts = cycleState?.drafts ?? []
  const cycleHistory = cycleState?.history ?? []
  const adherence = cycleState?.adherence ?? null

  return (
    <div className="page-stack plan-page">
      <header className="page-header inline-header">
        <div>
          <span>{t('plan.eyebrow')}</span>
          <h1>{t('plan.title')}</h1>
        </div>
        <div className="progress-toolbar">
          {activeCycle ? (
            <button
              type="button"
              className="primary-button"
              onClick={() => setShowCreateForm((v) => !v)}
            >
              <Plus size={16} />
              {t('planCycle.newCycle')}
            </button>
          ) : null}
          <button
            type="button"
            className="secondary-button"
            onClick={() =>
              navigate(
                `/coach?${new URLSearchParams({
                  surface: 'plan',
                  prompt: t('planCycle.askCoachGeneratePrompt'),
                }).toString()}`,
              )
            }
          >
            <Bot size={16} />
            {t('planCycle.askCoach')}
          </button>
        </div>
      </header>

      <WeeklyAutomationBanner onDraftGenerated={() => { loadCycle(selectedWeek) }} />

      {cycleError ? <ErrorState message={cycleError} /> : null}

      {showCreateForm ? (
        <form className="panel-card cycle-create-form" onSubmit={(e) => void handleCreateDraft(e)}>
          <h2>{t('planCycle.createTitle')}</h2>
          <p className="muted-copy">{t('planCycle.createHint')}</p>
          <div className="training-context-grid">
            <label>
              <span>{t('planCycle.cycleTitleLabel')}</span>
              <input
                type="text"
                maxLength={120}
                placeholder={t('planCycle.cycleTitlePlaceholder')}
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
              />
            </label>
            <label>
              <span>{t('planCycle.goalLabel')}</span>
              <select value={newGoal} onChange={(e) => setNewGoal(e.target.value as CycleGoalType)}>
                <option value="fat_loss">{t('profile.goalOptions.fat_loss')}</option>
                <option value="muscle_gain">{t('profile.goalOptions.muscle_gain')}</option>
                <option value="maintenance">{t('profile.goalOptions.maintenance')}</option>
              </select>
            </label>
            <label>
              <span>{t('planCycle.durationWeeks')}</span>
              <select value={newDuration} onChange={(e) => setNewDuration(Number(e.target.value))}>
                {[4, 6, 8, 12].map((w) => (
                  <option key={w} value={w}>
                    {t('planCycle.weeksOption', { count: w })}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="modal-actions">
            <button type="button" className="secondary-button" onClick={() => setShowCreateForm(false)}>
              {t('common.back')}
            </button>
            <button type="submit" className="primary-button" disabled={creating}>
              <Sparkles size={15} />
              {creating ? t('common.generating') : t('planCycle.generateDraft')}
            </button>
          </div>
        </form>
      ) : null}

      {drafts.length > 0 ? (
        <section className="panel-card draft-banner" aria-label={t('planCycle.pendingDrafts')}>
          {drafts.map((draft) => (
            <div key={draft.id} className="draft-banner-item">
              <div className="section-card-header inline-between">
                <div>
                  <span className="eyebrow-tag">{t('planCycle.draftBadge')}</span>
                  <h2>{draft.title}</h2>
                  <p className="muted-copy">
                    {t('planCycle.draftSummary', {
                      weeks: draft.duration_weeks,
                      start: draft.start_date,
                    })}
                  </p>
                </div>
                <div className="progress-toolbar">
                  <button
                    type="button"
                    className="primary-button"
                    disabled={busyAction !== null}
                    onClick={() => void handleActivate(draft.id)}
                  >
                    <Check size={15} />
                    {t('planCycle.confirmActivate')}
                  </button>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={busyAction !== null}
                    onClick={() => void handleDiscard(draft.id)}
                  >
                    <Trash2 size={15} />
                    {t('planCycle.discardDraft')}
                  </button>
                </div>
              </div>
              {Array.isArray(draft.rationale?.warnings) && draft.rationale.warnings.length > 0 ? (
                <ul className="draft-warnings">
                  {(draft.rationale.warnings as string[]).map((w, idx) => (
                    <li key={idx}>{w}</li>
                  ))}
                </ul>
              ) : null}
              {draft.week1_days?.length ? (
                <div className="week-strip compact">
                  {draft.week1_days.map((day) => (
                    <div key={day.id} className={`week-tile ${day.day_type}`}>
                      <span className="week-day-label">
                        {t(`auth.weekdays.${WEEKDAY_KEYS[day.day_of_week - 1]}`)}
                      </span>
                      <strong>{day.focus}</strong>
                      <small>{day.prescribed_exercises.length} {t('planCycle.exercisesUnit')}</small>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ))}
        </section>
      ) : null}

      {cycleLoading && !cycleState ? (
        <LoadingState label={t('plan.loadingHistory')} />
      ) : activeCycle ? (
        <section className="panel-card active-cycle-panel" aria-label={t('planCycle.activeCycle')}>
          <header className="section-card-header inline-between">
            <div>
              <span className="eyebrow-tag">
                <CalendarRange size={14} /> {t('planCycle.activeBadge')} ·{' '}
                {t('planCycle.weekOf', {
                  current: cycleState?.current_week ?? 1,
                  total: activeCycle.duration_weeks,
                })}
              </span>
              <h2>{activeCycle.title}</h2>
              {activeCycle.phases.length ? (
                <div className="phase-pills">
                  {activeCycle.phases.map((phase) => {
                    const isCurrent =
                      (cycleState?.current_week ?? 1) >= phase.start_week &&
                      (cycleState?.current_week ?? 1) <= phase.end_week
                    return (
                      <span key={phase.name} className={`phase-pill ${isCurrent ? 'current' : ''}`}>
                        {t('planCycle.phaseRange', {
                          name: phase.name,
                          start: phase.start_week,
                          end: phase.end_week,
                        })}
                      </span>
                    )
                  })}
                </div>
              ) : null}
            </div>

            <div className="cycle-week-meta">
              {adherence ? (
                <div className="cycle-adherence-box">
                  <span>
                    {t('planCycle.weekAdherence')}: <strong>{adherence.completed}/{adherence.planned} ({adherence.pct}%)</strong>
                  </span>
                  <div className="kpi-bar">
                    <span style={{ width: `${Math.min(100, adherence.pct)}%` }} />
                  </div>
                </div>
              ) : null}
              <select
                aria-label={t('planCycle.selectWeek')}
                value={cycleState?.current_week ?? 1}
                onChange={(e) => setSelectedWeek(Number(e.target.value))}
              >
                {Array.from({ length: activeCycle.duration_weeks }, (_, i) => i + 1).map((w) => (
                  <option key={w} value={w}>
                    {t('planCycle.weekOption', { week: w })}
                  </option>
                ))}
              </select>
            </div>
          </header>

          <div className="week-strip" role="list">
            {(cycleState?.days ?? []).map((day) => {
              const status = day.adherence ?? 'upcoming'
              const isSelected = selectedDay?.id === day.id
              return (
                <button
                  key={day.id}
                  type="button"
                  className={`week-tile ${status} ${isSelected ? 'selected' : ''}`}
                  onClick={() => setSelectedDayId(day.id)}
                >
                  <div className="week-tile-top">
                    <span className="week-day-label">
                      {t(`auth.weekdays.${WEEKDAY_KEYS[day.day_of_week - 1]}`)}
                    </span>
                    <span className={`adherence-dot ${status}`}>
                      {status === 'completed'
                        ? '✓'
                        : status === 'rest'
                          ? t('planCycle.badges.rest')
                          : status === 'skipped'
                            ? t('planCycle.badges.skipped')
                            : status === 'missed'
                              ? '!'
                              : '·'}
                    </span>
                  </div>
                  <strong>{day.focus}</strong>
                  <small>{day.scheduled_date.slice(5)}</small>
                </button>
              )
            })}
          </div>

          {selectedDay ? (
            <div className="selected-day-detail">
              <div className="section-card-header inline-between">
                <div>
                  <h3>
                    {selectedDay.scheduled_date} · {selectedDay.focus}
                  </h3>
                  <p className="muted-copy">{selectedDay.notes}</p>
                </div>
                <div className="progress-toolbar">
                  <span className={`adherence-pill ${selectedDay.adherence ?? 'upcoming'}`}>
                    {selectedDay.adherence === 'completed' ? <CheckCircle2 size={14} /> : null}
                    {t(`planCycle.status.${selectedDay.adherence ?? 'upcoming'}`)}
                  </span>
                  {selectedDay.day_type !== 'rest' ? (
                    <>
                      <button
                        type="button"
                        className="primary-button"
                        disabled={busyAction !== null}
                        onClick={() => void handlePrefillWorkout(selectedDay.id)}
                      >
                        <Dumbbell size={15} />
                        {t('planCycle.logByPlan')}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={busyAction !== null}
                        onClick={() => void handleToggleSkip(selectedDay)}
                      >
                        <SkipForward size={15} />
                        {selectedDay.status_override === 'skipped'
                          ? t('planCycle.unskipDay')
                          : t('planCycle.skipDay')}
                      </button>
                    </>
                  ) : null}
                </div>
              </div>

              {selectedDay.prescribed_exercises.length ? (
                <ul className="prescribed-list">
                  {selectedDay.prescribed_exercises.map((ex, idx) => (
                    <li key={`${ex.catalog_exercise_id ?? ex.name}-${idx}`}>
                      <div>
                        <strong>{ex.name}</strong>
                        <small className="muted-copy"> · {ex.primary_muscle}</small>
                        {ex.notes ? <p className="muted-copy">{ex.notes}</p> : null}
                      </div>
                      <span>
                        {ex.exercise_type === 'cardio'
                          ? `${ex.duration_min ?? 30} ${t('common.minutesShort')}`
                          : `${ex.sets} × ${ex.reps}${ex.target_weight_kg != null ? ` @ ${ex.target_weight_kg} kg` : ''}`}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted-copy">{t('planCycle.restDayCopy')}</p>
              )}
            </div>
          ) : null}
        </section>
      ) : (
        <section className="panel-card cold-start-box">
          <p>{t('planCycle.noActiveCycle')}</p>
          <button type="button" className="primary-button" onClick={() => setShowCreateForm(true)}>
            <Plus size={16} />
            {t('planCycle.newCycle')}
          </button>
        </section>
      )}

      <section className="content-panel">
        <h2>{t('plan.history')}</h2>
        {error ? <ErrorState message={error} /> : null}
        {cycleLoading && !cycleState ? <LoadingState label={t('plan.loadingHistory')} /> : null}
        {!cycleLoading && cycleHistory.length === 0 ? (
          <EmptyState label={t('planCycle.noCycleHistory')} />
        ) : null}
        {cycleHistory.length > 0 ? (
          <ul className="cycle-history-list">
            {cycleHistory.map((item) => (
              <li key={item.id} className="cycle-history-row">
                <div>
                  <strong>{item.title}</strong>
                  <small className="muted-copy">
                    {t('planCycle.cycleMeta', {
                      weeks: item.duration_weeks,
                      start: item.start_date,
                    })}
                  </small>
                </div>
                <span className={`cycle-status-pill ${item.status}`}>
                  {t(`planCycle.cycleStatus.${item.status}`, { defaultValue: item.status })}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        {!loading && plans.length > 0 ? (
          <details className="legacy-plans-details">
            <summary>{t('plan.legacyArchive', { count: plans.length })}</summary>
            <ul>
              {plans.map((item) => (
                <li key={item.plan_id}>
                  <Link to={`/plan/${item.plan_id}`}>
                    {item.plan_id} · {new Date(item.activated_at).toLocaleString()}
                  </Link>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </section>
    </div>
  )
}
