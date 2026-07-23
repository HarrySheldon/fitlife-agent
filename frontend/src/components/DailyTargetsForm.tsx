import { AlertTriangle, ChevronDown, History, RefreshCw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { DailyTargetValues, DailyTargetVersion, TargetPreview } from '../types'


interface DailyTargetsFormProps {
  currentTarget: DailyTargetVersion
  preview: TargetPreview | null
  restriction: string | null
  history: DailyTargetVersion[]
  historyLoading: boolean
  historyError: string | null
  stalePreview: boolean
  saving: boolean
  calculating: boolean
  confirming: boolean
  onCalculate: (manualTargets?: DailyTargetValues) => Promise<TargetPreview>
  onConfirm: (acknowledgeWarnings: boolean) => Promise<DailyTargetVersion>
}

export function DailyTargetsForm({
  currentTarget,
  preview,
  restriction,
  history,
  historyLoading,
  historyError,
  stalePreview,
  saving,
  calculating,
  confirming,
  onCalculate,
  onConfirm,
}: DailyTargetsFormProps) {
  const { t, i18n } = useTranslation()
  const [manualMode, setManualMode] = useState(false)
  const [manualTargets, setManualTargets] = useState<DailyTargetValues>(targetValues(currentTarget))
  const [acknowledged, setAcknowledged] = useState(false)
  const [previewDirty, setPreviewDirty] = useState(false)
  const manualModeRef = useRef(manualMode)
  const manualTargetsRef = useRef(manualTargets)
  const busy = saving || calculating || confirming
  manualModeRef.current = manualMode
  manualTargetsRef.current = manualTargets

  useEffect(() => {
    if (!manualMode) setManualTargets(targetValues(currentTarget))
  }, [currentTarget, manualMode])

  useEffect(() => {
    setAcknowledged(false)
    if (!preview) return
    if (manualModeRef.current) {
      const matchesManualDraft = (
        preview.source === 'manual'
        && targetValuesEqual(preview.targets, manualTargetsRef.current)
      )
      setPreviewDirty(!matchesManualDraft)
      return
    }
    if (preview.source === 'deterministic_calculation') setPreviewDirty(false)
  }, [preview?.preview_token])

  async function calculate() {
    await onCalculate(manualMode ? manualTargets : undefined)
  }

  function updateManualTarget(key: keyof DailyTargetValues, value: number) {
    setManualTargets((current) => ({ ...current, [key]: value }))
    setAcknowledged(false)
    setPreviewDirty(true)
  }

  const confirmablePreview = previewDirty ? null : preview

  return (
    <div className="daily-target-editor">
      <div className="profile-target-values" aria-label={t('profile.currentTargets')}>
        <TargetValue label={t('profile.calories')} value={currentTarget.calories} unit="kcal" />
        <TargetValue label={t('profile.carbs')} value={currentTarget.carbs} unit="g" />
        <TargetValue label={t('profile.protein')} value={currentTarget.protein} unit="g" />
        <TargetValue label={t('profile.fat')} value={currentTarget.fat} unit="g" />
      </div>

      <div className="target-edit-controls">
        <label className="profile-checkbox">
          <input
            type="checkbox"
            checked={manualMode}
            disabled={busy}
            onChange={(event) => {
              setManualMode(event.target.checked)
              setManualTargets(targetValues(currentTarget))
              setAcknowledged(false)
              setPreviewDirty(true)
            }}
          />
          <span>{t('profile.manualTargets')}</span>
        </label>

        {manualMode ? (
          <div className="profile-target-inputs">
            <TargetInput label={t('profile.caloriesInput')} value={manualTargets.calories} min={800} max={6000} disabled={busy} onChange={(value) => updateManualTarget('calories', value)} />
            <TargetInput label={t('profile.carbsInput')} value={manualTargets.carbs} min={0} max={1000} disabled={busy} onChange={(value) => updateManualTarget('carbs', value)} />
            <TargetInput label={t('profile.proteinInput')} value={manualTargets.protein} min={20} max={400} disabled={busy} onChange={(value) => updateManualTarget('protein', value)} />
            <TargetInput label={t('profile.fatInput')} value={manualTargets.fat} min={10} max={300} disabled={busy} onChange={(value) => updateManualTarget('fat', value)} />
          </div>
        ) : null}

        <button
          className="secondary-button"
          type="button"
          disabled={busy || Boolean(restriction && !manualMode)}
          onClick={() => void calculate().catch(() => undefined)}
        >
          <RefreshCw size={16} aria-hidden="true" />
          {calculating
            ? t('profile.calculatingTargets')
            : manualMode
              ? t('profile.reviewManualTargets')
              : t('profile.recalculateTargets')}
        </button>
      </div>

      {restriction ? (
        <div className="profile-restriction" role="alert">
          <AlertTriangle size={20} aria-hidden="true" />
          <div>
            <strong>{t('profile.restrictionTitle')}</strong>
            <p>{t('profile.restrictionMessage')}</p>
          </div>
        </div>
      ) : null}

      {confirmablePreview ? (
        <section className="target-preview" aria-live="polite">
          <header>
            <div>
              <span>{t('profile.pendingConfirmation')}</span>
              <h3>{t('profile.previewTitle')}</h3>
            </div>
            <small>{t(`profile.targetSources.${confirmablePreview.source}`)}</small>
          </header>
          <div className="profile-target-values">
            <TargetValue label={t('profile.calories')} value={confirmablePreview.targets.calories} unit="kcal" />
            <TargetValue label={t('profile.carbs')} value={confirmablePreview.targets.carbs} unit="g" />
            <TargetValue label={t('profile.protein')} value={confirmablePreview.targets.protein} unit="g" />
            <TargetValue label={t('profile.fat')} value={confirmablePreview.targets.fat} unit="g" />
          </div>
          <p className="profile-target-disclaimer">{t('profile.targetDisclaimer')}</p>
          {confirmablePreview.requires_confirmation ? (
            <div className="profile-target-warnings">
              <strong>{t('profile.reviewWarnings')}</strong>
              {confirmablePreview.warnings.length ? (
                <ul>
                  {confirmablePreview.warnings.map((warning) => (
                    <li key={warning}>{t(`onboarding.warnings.${warning}`)}</li>
                  ))}
                </ul>
              ) : null}
              <label className="profile-checkbox">
                <input
                  type="checkbox"
                  checked={acknowledged}
                  onChange={(event) => setAcknowledged(event.target.checked)}
                />
                <span>{t('onboarding.confirm.acknowledge')}</span>
              </label>
            </div>
          ) : null}
          <button
            className="primary-button"
            type="button"
            disabled={busy || (confirmablePreview.requires_confirmation && !acknowledged)}
            onClick={() => void onConfirm(acknowledged).catch(() => undefined)}
          >
            {confirming ? t('common.submitting') : t('profile.confirmTargets')}
          </button>
        </section>
      ) : null}

      {stalePreview ? (
        <div className="inline-error" role="alert">{t('onboarding.stalePreview')}</div>
      ) : null}
      <details className="target-history">
        <summary>
          <History size={17} aria-hidden="true" />
          <span>{t('profile.targetHistory')}</span>
          <ChevronDown size={17} aria-hidden="true" />
        </summary>
        {historyLoading ? <p>{t('common.loading')}...</p> : null}
        {historyError ? <p className="form-error">{historyError}</p> : null}
        {!historyLoading && !historyError ? (
          history.length ? (
            <ol>
              {history.map((item) => (
                <li key={item.id}>
                  <time dateTime={item.effective_from}>
                    {new Intl.DateTimeFormat(i18n.language, {
                      year: 'numeric',
                      month: 'short',
                      day: 'numeric',
                    }).format(new Date(item.effective_from))}
                  </time>
                  <span>{[
                    `${item.calories} kcal`,
                    `${item.carbs} g ${t('profile.carbs').toLocaleLowerCase()}`,
                    `${item.protein} g ${t('profile.protein').toLocaleLowerCase()}`,
                    `${item.fat} g ${t('profile.fat').toLocaleLowerCase()}`,
                  ].join(' | ')}</span>
                  <small>{t(`profile.targetSources.${item.source}`)}</small>
                </li>
              ))}
            </ol>
          ) : <p>{t('profile.noTargetHistory')}</p>
        ) : null}
      </details>
    </div>
  )
}

function TargetValue({ label, value, unit }: { label: string, value: number, unit: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value} <small>{unit}</small></strong>
    </div>
  )
}

function TargetInput({
  label,
  value,
  min,
  max,
  disabled,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  disabled: boolean
  onChange: (value: number) => void
}) {
  return (
    <label>
      <span>{label}</span>
      <input
        required
        type="number"
        min={min}
        max={max}
        disabled={disabled}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  )
}

function targetValues(target: DailyTargetVersion): DailyTargetValues {
  return {
    calories: target.calories,
    carbs: target.carbs,
    protein: target.protein,
    fat: target.fat,
  }
}

function targetValuesEqual(left: DailyTargetValues, right: DailyTargetValues): boolean {
  return left.calories === right.calories
    && left.carbs === right.carbs
    && left.protein === right.protein
    && left.fat === right.fat
}
