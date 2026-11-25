import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { displayWeight, kgToLb, metricWeight, weightUnit } from '../domain/units'
import type { OverallGoal, OverallGoalVersion, OverallGoalVersionUpdate, UnitSystem } from '../types'


interface OverallGoalFormProps {
  goal: OverallGoalVersion
  saving: boolean
  unitSystem?: UnitSystem
  onSave: (goal: OverallGoalVersionUpdate) => Promise<unknown>
}

function formatTargetWeightInput(valueKg: number | null | undefined, unitSystem: UnitSystem): string {
  if (valueKg == null) return ''
  return String(displayWeight(valueKg, unitSystem))
}

export function OverallGoalForm({ goal, saving, unitSystem = 'metric', onSave }: OverallGoalFormProps) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState<OverallGoal>(goal.goal)
  const [targetWeightInput, setTargetWeightInput] = useState<string>(() => (
    formatTargetWeightInput(goal.target_weight_kg, unitSystem)
  ))

  useEffect(() => {
    setDraft(goal.goal)
    setTargetWeightInput(formatTargetWeightInput(goal.target_weight_kg, unitSystem))
  }, [goal.id, goal.target_weight_kg, unitSystem])

  const unit = weightUnit(unitSystem)
  const weightMin = unitSystem === 'imperial' ? Math.ceil(kgToLb(30) * 10) / 10 : 30
  const weightMax = unitSystem === 'imperial' ? Math.floor(kgToLb(300) * 10) / 10 : 300

  return (
    <form
      className="profile-form"
      onSubmit={(event) => {
        event.preventDefault()
        const trimmed = targetWeightInput.trim()
        const parsedKg = trimmed === '' ? null : Math.round(metricWeight(Number(trimmed), unitSystem) * 10) / 10
        void Promise.resolve(onSave({
          goal: draft,
          target_weight_kg: parsedKg,
          effective_from: new Date().toISOString(),
        })).catch(() => undefined)
      }}
    >
      <fieldset className="profile-choice-fieldset">
        <legend>{t('profile.overallGoalChoice')}</legend>
        <div className="profile-goal-options">
          {(['fat_loss', 'maintenance', 'muscle_gain'] as const).map((value) => (
            <label key={value}>
              <input
                type="radio"
                name="overall-goal"
                value={value}
                checked={draft === value}
                disabled={saving}
                onChange={() => setDraft(value)}
              />
              <span>{t(`profile.goalOptions.${value}`)}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <div className="profile-field-grid">
        <div>
          <label>
            <span>{t('profile.targetWeightOptional', { unit })}</span>
            <input
              type="number"
              min={weightMin}
              max={weightMax}
              step="0.1"
              disabled={saving}
              aria-describedby="overall-goal-target-weight-hint"
              placeholder={t('profile.targetWeightPlaceholder')}
              value={targetWeightInput}
              onChange={(event) => setTargetWeightInput(event.target.value)}
            />
          </label>
          <small id="overall-goal-target-weight-hint" className="field-hint">
            {t('profile.targetWeightHint')}
          </small>
        </div>
      </div>
      <div className="profile-form-actions">
        <button className="primary-button" type="submit" disabled={saving}>
          {saving ? t('common.saving') : t('profile.saveOverallGoal')}
        </button>
      </div>
    </form>
  )
}
