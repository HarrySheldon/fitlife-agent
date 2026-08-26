import { Bot, Pencil } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { CoachDrawer } from '../components/CoachDrawer'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { cmToFeetInches, displayWeight, weightUnit } from '../domain/units'
import { usePreferences } from '../hooks/usePreferences'
import { useProfileSetup } from '../hooks/useProfileSetup'

export function Profile() {
  const { t } = useTranslation()
  const { preferences } = usePreferences()
  const { setup, loading, error } = useProfileSetup()
  const [coachOpen, setCoachOpen] = useState(false)
  const coachTriggerRef = useRef<HTMLButtonElement>(null)

  if (loading) return <LoadingState label={t('profile.loading')} />
  if (error && !setup) return <ErrorState message={error} />
  if (!setup?.profile || !setup.goal || !setup.target) return <ErrorState message={t('profile.incompleteSetup')} />

  const { profile, goal, target } = setup
  return <div className="page-stack profile-page">
    <header className="page-header inline-header">
      <div><span>{t('profile.eyebrow')}</span><h1>{t('profile.title')}</h1></div>
      <Link className="primary-button" to="/profile/edit"><Pencil size={17} />{t('profile.editProfile')}</Link>
    </header>
    <main className="profile-summary" aria-label={t('profile.summary')}>
      <dl>
        <Summary label={t('profile.age')} value={String(profile.age)} />
        <Summary label={t('profile.heightSummary')} value={height(profile.height_cm, preferences.unit_system)} />
        <Summary label={t('profile.weightSummary')} value={`${displayWeight(profile.weight_kg, preferences.unit_system)} ${weightUnit(preferences.unit_system)}`} />
        <Summary label={t('profile.overallGoal')} value={t(`profile.goalOptions.${goal.goal}`)} />
        <Summary label={t('profile.dailyCalories')} value={`${target.calories} kcal`} />
        <Summary label={t('profile.dailyProtein')} value={`${target.protein} g`} />
      </dl>
      <p>{t('profile.coachAdviceOnly')}</p>
      <button ref={coachTriggerRef} className="secondary-button" type="button" onClick={() => setCoachOpen(true)}>
        <Bot size={17} />{t('profile.askCoachAdvice')}
      </button>
    </main>
    <CoachDrawer
      open={coachOpen}
      onClose={() => setCoachOpen(false)}
      returnFocusRef={coachTriggerRef}
      surface="profile"
      actions={[{ action: 'suggest_targets', label: t('profile.askCoachAdvice') }]}
    />
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
