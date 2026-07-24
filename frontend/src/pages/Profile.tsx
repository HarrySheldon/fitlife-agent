import { Activity, Bot, Dumbbell, Target, UserRound } from 'lucide-react'
import type { ReactNode } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { CoachPanel } from '../components/CoachPanel'
import { DailyTargetsForm } from '../components/DailyTargetsForm'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { OverallGoalForm } from '../components/OverallGoalForm'
import { ProfileDetailsForm } from '../components/ProfileDetailsForm'
import { useProfile } from '../hooks/useProfile'
import { useProfileSetup } from '../hooks/useProfileSetup'
import { usePreferences } from '../hooks/usePreferences'
import { api } from '../services/api'
import type { DailyTargetVersion, UserProfile } from '../types'

export function Profile() {
  const { t } = useTranslation()
  const { preferences } = usePreferences()
  const legacy = useProfile()
  const {
    setup,
    preview,
    restriction,
    loading,
    saving,
    calculating,
    confirming,
    stalePreview,
    error,
    updateProfile,
    updateOverallGoal,
    calculateTargets,
    confirmTargets,
  } = useProfileSetup()
  const [history, setHistory] = useState<DailyTargetVersion[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [legacyPersonalizationError, setLegacyPersonalizationError] = useState<string | null>(null)
  const [legacyPersonalizationSaving, setLegacyPersonalizationSaving] = useState(false)
  const mounted = useRef(false)
  const historyRequestSequence = useRef(0)
  const legacyPersonalizationLock = useRef(false)
  const confirmationAttempt = useRef<{
    previewToken: string
    effectiveFrom: string
  } | null>(null)

  useEffect(() => {
    if (
      stalePreview
      || !preview
      || confirmationAttempt.current?.previewToken !== preview.preview_token
    ) {
      confirmationAttempt.current = null
    }
  }, [preview, stalePreview])

  const loadHistory = useCallback(async () => {
    if (!mounted.current) return
    const requestSequence = historyRequestSequence.current + 1
    historyRequestSequence.current = requestSequence
    setHistoryLoading(true)
    setHistoryError(null)
    try {
      const items = await api.targetHistory()
      if (mounted.current && historyRequestSequence.current === requestSequence) {
        setHistory(items)
      }
    } catch (cause) {
      if (mounted.current && historyRequestSequence.current === requestSequence) {
        setHistoryError(cause instanceof Error ? cause.message : String(cause))
      }
    } finally {
      if (mounted.current && historyRequestSequence.current === requestSequence) {
        setHistoryLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    void loadHistory()
    return () => {
      mounted.current = false
      historyRequestSequence.current += 1
    }
  }, [loadHistory])

  async function confirm(acknowledgeWarnings: boolean) {
    if (!preview) throw new Error('TARGET_PREVIEW_REQUIRED')
    if (confirmationAttempt.current?.previewToken !== preview.preview_token) {
      confirmationAttempt.current = {
        previewToken: preview.preview_token,
        effectiveFrom: new Date().toISOString(),
      }
    }
    const target = await confirmTargets({
      effectiveFrom: confirmationAttempt.current.effectiveFrom,
      acknowledgeWarnings,
    })
    confirmationAttempt.current = null
    await loadHistory()
    return target
  }

  async function saveLegacyPersonalization(update: Pick<UserProfile, 'experience_level' | 'training_preference'>) {
    if (legacyPersonalizationLock.current) return
    legacyPersonalizationLock.current = true
    setLegacyPersonalizationError(null)
    setLegacyPersonalizationSaving(true)
    try {
      await legacy.save(update)
    } catch (cause) {
      if (mounted.current) {
        setLegacyPersonalizationError(cause instanceof Error ? cause.message : String(cause))
      }
      throw cause
    } finally {
      legacyPersonalizationLock.current = false
      if (mounted.current) setLegacyPersonalizationSaving(false)
    }
  }

  if (loading) return <LoadingState label={t('profile.loading')} />
  if (error && !setup) return <ErrorState message={error} />
  if (!setup?.profile || !setup.goal || !setup.target) return <ErrorState message={t('profile.incompleteSetup')} />

  return (
    <div className="page-stack profile-page">
      <header className="page-header">
        <span>{t('profile.eyebrow')}</span>
        <h1>{t('profile.title')}</h1>
      </header>
      {error ? <div className="inline-error profile-global-feedback" role="alert">{error}</div> : null}
      <main className="profile-workspace">
        <ProfileSection
          icon={UserRound}
          title={t('profile.bodyProfile')}
          description={t('profile.bodyProfileDescription')}
        >
          <ProfileDetailsForm
            profile={setup.profile}
            unitSystem={preferences.unit_system}
            saving={saving}
            onSave={updateProfile}
          />
        </ProfileSection>

        <ProfileSection
          icon={Activity}
          title={t('profile.overallGoal')}
          description={t('profile.overallGoalDescription')}
        >
          <OverallGoalForm goal={setup.goal} saving={saving} onSave={updateOverallGoal} />
        </ProfileSection>

        <ProfileSection
          icon={Target}
          title={t('profile.dailyTargets')}
          description={t('profile.dailyTargetsDescription')}
        >
          <DailyTargetsForm
            currentTarget={setup.target}
            preview={preview}
            restriction={restriction}
            history={history}
            historyLoading={historyLoading}
            historyError={historyError}
            stalePreview={stalePreview}
            saving={saving}
            calculating={calculating}
            confirming={confirming}
            onCalculate={calculateTargets}
            onConfirm={confirm}
          />
        </ProfileSection>

        <ProfileSection
          icon={Dumbbell}
          title={t('profile.trainingPersonalization')}
          description={t('profile.trainingPersonalizationDescription')}
          compact
        >
          {legacy.loading ? <LoadingState label={t('profile.loadingPersonalization')} /> : null}
          {legacyPersonalizationError || legacy.error ? (
            <div className="inline-error" role="alert">
              {legacyPersonalizationError ?? legacy.error}
            </div>
          ) : null}
          {legacy.profile ? (
            <LegacyPersonalizationForm
              profile={legacy.profile}
              saving={legacy.saving || legacyPersonalizationSaving}
              onSave={saveLegacyPersonalization}
            />
          ) : null}
        </ProfileSection>

        <section className="profile-coach-section" aria-labelledby="profile-coach-title">
          <header>
            <Bot size={20} aria-hidden="true" />
            <div>
              <h2 id="profile-coach-title">{t('profile.coachAdviceTitle')}</h2>
              <p>{t('profile.coachAdviceOnly')}</p>
            </div>
          </header>
          <CoachPanel surface="profile" actions={[{ action: 'suggest_targets', label: t('profile.askCoachAdvice') }]} />
        </section>
      </main>
    </div>
  )
}

function ProfileSection({
  icon: Icon,
  title,
  description,
  compact = false,
  children,
}: {
  icon: typeof UserRound
  title: string
  description: string
  compact?: boolean
  children: ReactNode
}) {
  return (
    <section className={`profile-section${compact ? ' compact' : ''}`}>
      <header className="profile-section-heading">
        <Icon size={20} aria-hidden="true" />
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
      </header>
      <div className="profile-section-content">{children}</div>
    </section>
  )
}

function LegacyPersonalizationForm({
  profile,
  saving,
  onSave,
}: {
  profile: UserProfile
  saving: boolean
  onSave: (profile: Pick<UserProfile, 'experience_level' | 'training_preference'>) => Promise<void>
}) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState(profile)

  useEffect(() => setDraft(profile), [profile])

  return (
    <form
      className="legacy-personalization-form"
      onSubmit={(event) => {
        event.preventDefault()
        void Promise.resolve(onSave({
          experience_level: draft.experience_level,
          training_preference: draft.training_preference,
        })).catch(() => undefined)
      }}
    >
      <label>
        <span>{t('profile.experience')}</span>
        <select
          value={draft.experience_level}
          disabled={saving}
          onChange={(event) => setDraft((current) => ({
            ...current,
            experience_level: event.target.value as UserProfile['experience_level'],
          }))}
        >
          <option value="beginner">{t('profile.beginner')}</option>
          <option value="novice">{t('profile.novice')}</option>
          <option value="experienced">{t('profile.experienced')}</option>
        </select>
      </label>
      <label>
        <span>{t('profile.trainingFocus')}</span>
        <select
          value={draft.training_preference}
          disabled={saving}
          onChange={(event) => setDraft((current) => ({
            ...current,
            training_preference: event.target.value as UserProfile['training_preference'],
          }))}
        >
          <option value="strength">{t('profile.strength')}</option>
          <option value="cardio">{t('profile.cardio')}</option>
          <option value="mixed">{t('profile.mixed')}</option>
        </select>
      </label>
      <button className="secondary-button" type="submit" disabled={saving}>
        {saving ? t('common.saving') : t('profile.saveTrainingPersonalization')}
      </button>
    </form>
  )
}
