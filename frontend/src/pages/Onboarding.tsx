import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Check,
  HeartPulse,
  Ruler,
  Target,
  UserRound,
} from 'lucide-react'
import type { FormEvent } from 'react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useNavigate } from 'react-router-dom'

import { useProfileSetup } from '../hooks/useProfileSetup'
import { ApiRequestError } from '../services/api'
import type {
  ActivityLevel,
  DailyTargetValues,
  EnergyParameter,
  OverallGoal,
  ProfileVersionUpdate,
  SafetyCondition,
  TargetPreview,
} from '../types'


type Step = 0 | 1 | 2 | 3

interface ProfileFields {
  age: number
  heightCm: number
  weightKg: number
  energyParameter: EnergyParameter
  activityLevel: ActivityLevel
  autoTargetDisabled: boolean
  safetyConditions: SafetyCondition[]
}

const defaultProfile: ProfileFields = {
  age: 30,
  heightCm: 175,
  weightKg: 70,
  energyParameter: 'neutral',
  activityLevel: 'moderate',
  autoTargetDisabled: false,
  safetyConditions: [],
}

const emptyTargets: DailyTargetValues = {
  calories: 2000,
  carbs: 250,
  protein: 120,
  fat: 60,
}

export function Onboarding() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
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
  const initialized = useRef(false)
  const savedActivity = useRef<ActivityLevel | null>(null)
  const [step, setStep] = useState<Step>(0)
  const [profile, setProfile] = useState<ProfileFields>(defaultProfile)
  const [goal, setGoal] = useState<OverallGoal>('maintenance')
  const [manualMode, setManualMode] = useState(false)
  const [deterministicTargets, setDeterministicTargets] = useState<DailyTargetValues>(emptyTargets)
  const [manualTargets, setManualTargets] = useState<DailyTargetValues>(emptyTargets)
  const [acknowledged, setAcknowledged] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)

  useEffect(() => {
    if (!setup || initialized.current) return
    initialized.current = true
    if (setup.profile) {
      setProfile({
        age: setup.profile.age,
        heightCm: setup.profile.height_cm,
        weightKg: setup.profile.weight_kg,
        energyParameter: setup.profile.energy_parameter,
        activityLevel: setup.profile.activity_level,
        autoTargetDisabled: setup.profile.auto_target_disabled,
        safetyConditions: setup.profile.safety_conditions,
      })
      savedActivity.current = setup.profile.activity_level
    }
    if (setup.goal) setGoal(setup.goal.goal)
    if (setup.target) {
      const values = targetValues(setup.target)
      setManualTargets(values)
      if (setup.target.source === 'deterministic_calculation') {
        setDeterministicTargets(values)
      }
    }
  }, [setup])

  useEffect(() => {
    if (!preview) return
    if (preview.source === 'deterministic_calculation') {
      setDeterministicTargets(preview.targets)
    } else {
      setManualTargets(preview.targets)
    }
  }, [preview])

  useEffect(() => {
    setAcknowledged(false)
  }, [
    preview?.preview_token,
    manualTargets.calories,
    manualTargets.carbs,
    manualTargets.protein,
    manualTargets.fat,
  ])

  if (loading) {
    return <div className="state-box onboarding-gate-state">{t('onboarding.loading')}...</div>
  }

  if (setup?.setup_complete) {
    return <Navigate to="/" replace />
  }

  const busy = saving || calculating || confirming
  const progress = [
    { label: t('onboarding.steps.profile'), icon: UserRound },
    { label: t('onboarding.steps.goal'), icon: Activity },
    { label: t('onboarding.steps.targets'), icon: Target },
    { label: t('onboarding.steps.confirm'), icon: Check },
  ]

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLocalError(null)
    try {
      await updateProfile(profilePayload(profile))
      savedActivity.current = profile.activityLevel
      setStep(1)
    } catch (cause) {
      setLocalError((cause as Error).message)
    }
  }

  async function saveGoalAndCalculate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLocalError(null)
    try {
      let result: TargetPreview | null = null
      let blocked: string | null = null
      if (savedActivity.current !== profile.activityLevel) {
        const mutation = await updateProfile(profilePayload(profile))
        savedActivity.current = profile.activityLevel
        result = mutation.recalculation_preview
        blocked = mutation.recalculation_restriction
      }
      const mutation = await updateOverallGoal({
        goal,
        effective_from: effectiveFrom(),
      })
      result = mutation.recalculation_preview ?? result
      blocked = mutation.recalculation_restriction ?? blocked
      if (!result && !blocked) result = await calculateTargets()
      if (result) {
        setDeterministicTargets(result.targets)
        setManualTargets(result.targets)
      }
      setManualMode(false)
      setAcknowledged(false)
      setStep(2)
    } catch (cause) {
      setLocalError((cause as Error).message)
    }
  }

  async function reviewTargets(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLocalError(null)
    try {
      if (manualMode) {
        const result = await calculateTargets(manualTargets)
        setManualTargets(result.targets)
      } else {
        const result = await calculateTargets()
        setDeterministicTargets(result.targets)
      }
      setAcknowledged(false)
      setStep(3)
    } catch (cause) {
      setLocalError((cause as Error).message)
    }
  }

  async function finish() {
    setLocalError(null)
    try {
      await confirmTargets({
        effectiveFrom: effectiveFrom(),
        acknowledgeWarnings: acknowledged,
      })
      navigate('/', { replace: true })
    } catch (cause) {
      if (
        cause instanceof ApiRequestError
        && (cause.code === 'TARGET_PREVIEW_STALE' || cause.status === 412)
      ) {
        setLocalError(null)
        setStep(2)
        return
      }
      setLocalError((cause as Error).message)
    }
  }

  return (
    <main className="onboarding-shell">
      <header className="onboarding-topbar">
        <div className="brand-block">
          <div className="brand-mark">FL</div>
          <div>
            <strong>FitLife Agent</strong>
            <span>{t('onboarding.brandLine')}</span>
          </div>
        </div>
        <span className="onboarding-step-count">
          {t('onboarding.stepCount', { current: step + 1, total: progress.length })}
        </span>
      </header>

      <ol className="onboarding-progress" aria-label={t('onboarding.progressLabel')}>
        {progress.map(({ label, icon: Icon }, index) => (
          <li
            className={index < step ? 'complete' : index === step ? 'active' : ''}
            aria-current={index === step ? 'step' : undefined}
            key={label}
          >
            <span><Icon size={17} aria-hidden="true" /></span>
            <strong>{label}</strong>
          </li>
        ))}
      </ol>

      <div className="onboarding-workspace">
        <aside className="onboarding-context">
          <span>{t('onboarding.eyebrow')}</span>
          <h1>{t('onboarding.title')}</h1>
          <p>{t('onboarding.context')}</p>
          <div className="onboarding-context-rule" />
          <small>{t('onboarding.adultOnly')}</small>
        </aside>

        <section className="onboarding-task" aria-live="polite">
          {step === 0 ? (
            <form onSubmit={(event) => void saveProfile(event)}>
              <TaskHeading icon={Ruler} title={t('onboarding.profile.title')} />
              <div className="onboarding-fields two-column">
                <NumberField
                  label={t('onboarding.profile.age')}
                  value={profile.age}
                  min={18}
                  max={100}
                  onChange={(age) => setProfile((current) => ({ ...current, age }))}
                />
                <NumberField
                  label={t('onboarding.profile.height')}
                  value={profile.heightCm}
                  min={120}
                  max={230}
                  step={0.1}
                  onChange={(heightCm) => setProfile((current) => ({ ...current, heightCm }))}
                />
                <NumberField
                  label={t('onboarding.profile.weight')}
                  value={profile.weightKg}
                  min={30}
                  max={300}
                  step={0.1}
                  onChange={(weightKg) => setProfile((current) => ({ ...current, weightKg }))}
                />
                <fieldset className="onboarding-fieldset">
                  <legend>{t('onboarding.profile.energyParameter')}</legend>
                  <div className="onboarding-segmented three">
                    {(['female', 'neutral', 'male'] as const).map((value) => (
                      <label key={value}>
                        <input
                          type="radio"
                          name="energyParameter"
                          value={value}
                          checked={profile.energyParameter === value}
                          onChange={() => setProfile((current) => ({ ...current, energyParameter: value }))}
                        />
                        <span>{t(`onboarding.profile.energy.${value}`)}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              </div>
              <TaskFeedback error={localError ?? error} stale={stalePreview} />
              <TaskActions busy={busy} primaryLabel={t('onboarding.continue')} />
            </form>
          ) : null}

          {step === 1 ? (
            <form onSubmit={(event) => void saveGoalAndCalculate(event)}>
              <TaskHeading icon={Activity} title={t('onboarding.goal.title')} />
              <fieldset className="onboarding-fieldset">
                <legend>{t('onboarding.goal.overall')}</legend>
                <div className="onboarding-segmented goal">
                  {(['fat_loss', 'maintenance', 'muscle_gain'] as const).map((value) => (
                    <label key={value}>
                      <input
                        type="radio"
                        name="goal"
                        value={value}
                        checked={goal === value}
                        onChange={() => setGoal(value)}
                      />
                      <span>{t(`onboarding.goal.options.${value}`)}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
              <label className="onboarding-field">
                <span>{t('onboarding.goal.activity')}</span>
                <select
                  value={profile.activityLevel}
                  onChange={(event) => setProfile((current) => ({
                    ...current,
                    activityLevel: event.target.value as ActivityLevel,
                  }))}
                >
                  {(['sedentary', 'light', 'moderate', 'high'] as const).map((value) => (
                    <option value={value} key={value}>{t(`onboarding.goal.activityOptions.${value}`)}</option>
                  ))}
                </select>
              </label>
              <TaskFeedback error={localError ?? error} stale={stalePreview} />
              <TaskActions
                busy={busy}
                primaryLabel={t('onboarding.goal.calculate')}
                onBack={() => setStep(0)}
              />
            </form>
          ) : null}

          {step === 2 ? (
            restriction ? (
              <div className="onboarding-restriction" role="alert">
                <HeartPulse size={34} aria-hidden="true" />
                <h2>{t('onboarding.restriction.title')}</h2>
                <p>{t('onboarding.restriction.message')}</p>
                <button className="secondary-button" type="button" onClick={() => setStep(1)}>
                  <ArrowLeft size={17} aria-hidden="true" />
                  {t('common.back')}
                </button>
              </div>
            ) : (
              <form onSubmit={(event) => void reviewTargets(event)}>
                <TaskHeading icon={Target} title={t('onboarding.targets.title')} />
                <p className="onboarding-advice">{t('onboarding.targets.disclaimer')}</p>
                <label className="onboarding-manual-toggle">
                  <input
                    type="checkbox"
                    checked={manualMode}
                    onChange={(event) => {
                      setManualMode(event.target.checked)
                      setAcknowledged(false)
                    }}
                  />
                  <span>{t('onboarding.targets.manual')}</span>
                </label>
                <TargetFields
                  values={manualMode ? manualTargets : deterministicTargets}
                  readOnly={!manualMode}
                  onChange={setManualTargets}
                />
                <TaskFeedback error={localError ?? error} stale={stalePreview} />
                <TaskActions
                  busy={busy}
                  primaryLabel={t('onboarding.targets.review')}
                  onBack={() => setStep(1)}
                />
              </form>
            )
          ) : null}

          {step === 3 && preview ? (
            <div>
              <TaskHeading icon={Check} title={t('onboarding.confirm.title')} />
              <div className="onboarding-target-summary">
                <TargetValue label={t('onboarding.targets.calories')} value={preview.targets.calories} unit="kcal" locale={i18n.language} />
                <TargetValue label={t('onboarding.targets.carbs')} value={preview.targets.carbs} unit="g" locale={i18n.language} />
                <TargetValue label={t('onboarding.targets.protein')} value={preview.targets.protein} unit="g" locale={i18n.language} />
                <TargetValue label={t('onboarding.targets.fat')} value={preview.targets.fat} unit="g" locale={i18n.language} />
              </div>
              <p className="onboarding-advice">{t('onboarding.targets.disclaimer')}</p>
              {preview.warnings.length ? (
                <div className="onboarding-warnings">
                  <strong>{t('onboarding.confirm.warnings')}</strong>
                  <ul>
                    {preview.warnings.map((warning) => (
                      <li key={warning}>{t(`onboarding.warnings.${warning}`)}</li>
                    ))}
                  </ul>
                  <label>
                    <input
                      type="checkbox"
                      checked={acknowledged}
                      onChange={(event) => setAcknowledged(event.target.checked)}
                    />
                    <span>{t('onboarding.confirm.acknowledge')}</span>
                  </label>
                </div>
              ) : null}
              <TaskFeedback error={localError ?? error} stale={stalePreview} />
              <div className="onboarding-actions">
                <button className="secondary-button" type="button" disabled={busy} onClick={() => setStep(2)}>
                  <ArrowLeft size={17} aria-hidden="true" />
                  {t('common.back')}
                </button>
                <button
                  className="primary-button"
                  type="button"
                  disabled={busy || (preview.requires_confirmation && !acknowledged)}
                  onClick={() => void finish()}
                >
                  <span>{confirming ? t('common.submitting') : t('onboarding.confirm.submit')}</span>
                  <ArrowRight size={17} aria-hidden="true" />
                </button>
              </div>
            </div>
          ) : null}
        </section>
      </div>
    </main>
  )
}

function TaskHeading({ icon: Icon, title }: { icon: typeof UserRound, title: string }) {
  return (
    <header className="onboarding-task-heading">
      <Icon size={24} aria-hidden="true" />
      <h2>{title}</h2>
    </header>
  )
}

function NumberField({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step?: number
  onChange: (value: number) => void
}) {
  return (
    <label className="onboarding-field">
      <span>{label}</span>
      <input
        required
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  )
}

function TargetFields({
  values,
  readOnly,
  onChange,
}: {
  values: DailyTargetValues
  readOnly: boolean
  onChange: (values: DailyTargetValues) => void
}) {
  const { t } = useTranslation()
  const definitions = [
    ['calories', t('onboarding.targets.caloriesInput'), 800, 6000],
    ['carbs', t('onboarding.targets.carbsInput'), 0, 1000],
    ['protein', t('onboarding.targets.proteinInput'), 20, 400],
    ['fat', t('onboarding.targets.fatInput'), 10, 300],
  ] as const

  return (
    <div className="onboarding-target-fields">
      {definitions.map(([key, label, min, max]) => (
        <label className="onboarding-field" key={key}>
          <span>{label}</span>
          <input
            required
            readOnly={readOnly}
            type="number"
            min={min}
            max={max}
            value={values[key]}
            onChange={(event) => onChange({ ...values, [key]: Number(event.target.value) })}
          />
        </label>
      ))}
    </div>
  )
}

function TargetValue({
  label,
  value,
  unit,
  locale,
}: {
  label: string
  value: number
  unit: string
  locale: string
}) {
  return (
    <div>
      <span>{label}</span>
      <strong>{new Intl.NumberFormat(locale).format(value)} {unit}</strong>
    </div>
  )
}

function TaskActions({
  busy,
  primaryLabel,
  onBack,
}: {
  busy: boolean
  primaryLabel: string
  onBack?: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="onboarding-actions">
      {onBack ? (
        <button className="secondary-button" type="button" disabled={busy} onClick={onBack}>
          <ArrowLeft size={17} aria-hidden="true" />
          {t('common.back')}
        </button>
      ) : <span />}
      <button className="primary-button" type="submit" disabled={busy}>
        <span>{busy ? t('common.saving') : primaryLabel}</span>
        <ArrowRight size={17} aria-hidden="true" />
      </button>
    </div>
  )
}

function TaskFeedback({ error, stale }: { error: string | null, stale: boolean }) {
  const { t } = useTranslation()
  if (!error && !stale) return null
  return (
    <div className="inline-error" role="alert">
      {stale ? t('onboarding.stalePreview') : error}
    </div>
  )
}

function profilePayload(profile: ProfileFields): ProfileVersionUpdate {
  return {
    age: profile.age,
    height_cm: profile.heightCm,
    weight_kg: profile.weightKg,
    energy_parameter: profile.energyParameter,
    activity_level: profile.activityLevel,
    auto_target_disabled: profile.autoTargetDisabled,
    safety_conditions: profile.safetyConditions,
    effective_from: effectiveFrom(),
  }
}

function targetValues(values: DailyTargetValues): DailyTargetValues {
  return {
    calories: values.calories,
    carbs: values.carbs,
    protein: values.protein,
    fat: values.fat,
  }
}

function effectiveFrom(): string {
  return new Date().toISOString()
}
