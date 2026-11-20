import { Bot, Pencil } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { CoachDrawer } from '../components/CoachDrawer'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { cmToFeetInches, displayWeight, weightUnit } from '../domain/units'
import { usePreferences } from '../hooks/usePreferences'
import { useProfileSetup } from '../hooks/useProfileSetup'
import { useCoach } from '../hooks/useCoach'
import { progressApi, type TrainingContext } from '../services/progressApi'

export function Profile() {
  const { t } = useTranslation()
  const { preferences } = usePreferences()
  const coach = useCoach()
  const { setup, loading, error } = useProfileSetup()
  const [coachOpen, setCoachOpen] = useState(false)
  const [latestWeight, setLatestWeight] = useState<{ weight_kg: number; date: string } | null>(null)
  const [trainingCtx, setTrainingCtx] = useState<TrainingContext | null>(null)
  const coachTriggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    let active = true
    progressApi
      .listBodyMeasurements(365)
      .then((res) => {
        if (active && res.summary.latest_weight_kg != null && res.summary.latest_measured_date) {
          setLatestWeight({
            weight_kg: res.summary.latest_weight_kg,
            date: res.summary.latest_measured_date,
          })
        }
      })
      .catch(() => {
        // Optional enhancement; fall back to profile weight
      })
    progressApi
      .getTrainingContext()
      .then((res) => {
        if (active) setTrainingCtx(res.training_context)
      })
      .catch(() => {
        // Optional enhancement
      })
    return () => {
      active = false
    }
  }, [])

  if (loading) return <LoadingState label={t('profile.loading')} />
  if (error && !setup) return <ErrorState message={error} />
  if (!setup?.profile || !setup.goal || !setup.target) return <ErrorState message={t('profile.incompleteSetup')} />

  const { profile, goal, target } = setup
  const effectiveWeightKg = latestWeight?.weight_kg ?? profile.weight_kg
  return <div className="page-stack profile-page">
    <header className="page-header inline-header">
      <div><span>{t('profile.eyebrow')}</span><h1>{t('profile.title')}</h1></div>
      <Link className="primary-button" to="/profile/edit"><Pencil size={17} />{t('profile.editProfile')}</Link>
    </header>
    <main className="profile-summary" aria-label={t('profile.summary')}>
      <dl>
        <Summary label={t('profile.age')} value={String(profile.age)} />
        <Summary label={t('profile.heightSummary')} value={height(profile.height_cm, preferences.unit_system)} />
        <Summary
          label={t('profile.weightSummary')}
          value={
            latestWeight
              ? `${displayWeight(effectiveWeightKg, preferences.unit_system)} ${weightUnit(preferences.unit_system)} (${latestWeight.date})`
              : `${displayWeight(effectiveWeightKg, preferences.unit_system)} ${weightUnit(preferences.unit_system)}`
          }
        />
        <Summary label={t('profile.overallGoal')} value={t(`profile.goalOptions.${goal.goal}`)} />
        <Summary label={t('profile.dailyCalories')} value={`${target.calories} kcal`} />
        <Summary label={t('profile.dailyProtein')} value={`${target.protein} g`} />
      </dl>
      <p>{t('profile.coachAdviceOnly')}</p>
      <button ref={coachTriggerRef} className="secondary-button" type="button" disabled={Boolean(coach?.sending || coach?.active)} onClick={() => coach ? void coach.send({ question: t('profile.askCoachAdvice'), action: 'suggest_targets', surface: 'profile' }) : setCoachOpen(true)}>
        <Bot size={17} />{t('profile.askCoachAdvice')}
      </button>
    </main>
    {trainingCtx ? (
      <section className="panel-card" aria-label={t('trainingContext.title')}>
        <h2>{t('trainingContext.title')}</h2>
        <dl className="profile-summary">
          <Summary
            label={t('trainingContext.equipment')}
            value={trainingCtx.available_equipment.map((eq) => t(`trainingContext.equipmentOptions.${eq}`)).join(', ')}
          />
          <Summary
            label={t('trainingContext.weeklyDays')}
            value={`${trainingCtx.weekly_available_days}`}
          />
          <Summary
            label={t('trainingContext.durationMin')}
            value={`${trainingCtx.session_duration_min} ${t('common.minutesShort')}`}
          />
          <Summary
            label={t('trainingContext.experience')}
            value={t(`trainingContext.experienceOptions.${trainingCtx.experience_level}`)}
          />
        </dl>
      </section>
    ) : null}
    {!coach ? <CoachDrawer
      open={coachOpen}
      onClose={() => setCoachOpen(false)}
      returnFocusRef={coachTriggerRef}
      surface="profile"
      actions={[{ action: 'suggest_targets', label: t('profile.askCoachAdvice') }]}
    /> : null}
  </div>
}

function Summary({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>
}

function height(valueCm: number, unitSystem: 'metric' | 'imperial') {
  if (unitSystem === 'metric') return `${valueCm} cm`
  const value = cmToFeetInches(valueCm)
  return `${value.feet} ft ${Math.round(value.inches)} in`
}
