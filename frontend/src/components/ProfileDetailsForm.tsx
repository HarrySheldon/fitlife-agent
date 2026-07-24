import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { cmToFeetInches, displayWeight, feetInchesToCm, kgToLb, metricWeight, weightUnit } from '../domain/units'
import type { ProfileVersion, ProfileVersionUpdate, SafetyCondition, UnitSystem } from '../types'

const SAFETY_CONDITIONS: SafetyCondition[] = [
  'pregnancy',
  'breastfeeding',
  'eating_disorder_history',
  'medical_condition_affecting_nutrition',
]

interface ProfileDetailsFormProps {
  profile: ProfileVersion
  saving: boolean
  unitSystem?: UnitSystem
  onSave: (profile: ProfileVersionUpdate) => Promise<unknown>
}

export function ProfileDetailsForm({
  profile,
  saving,
  unitSystem = 'metric',
  onSave,
}: ProfileDetailsFormProps) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState(profile)
  const [validationError, setValidationError] = useState<string | null>(null)

  useEffect(() => {
    setDraft(profile)
    setValidationError(null)
  }, [profile.id])

  const height = cmToFeetInches(draft.height_cm)
  const unit = weightUnit(unitSystem)
  const weightMin = unitSystem === 'imperial' ? Math.ceil(kgToLb(30) * 10) / 10 : 30
  const weightMax = unitSystem === 'imperial' ? Math.floor(kgToLb(300) * 10) / 10 : 300

  return (
    <form
      className="profile-form"
      onSubmit={(event) => {
        event.preventDefault()
        if (unitSystem === 'imperial' && (draft.height_cm < 120 || draft.height_cm > 230)) {
          setValidationError(t('profile.imperialHeightRange'))
          return
        }
        setValidationError(null)
        void Promise.resolve(onSave({
          age: draft.age,
          height_cm: draft.height_cm,
          weight_kg: draft.weight_kg,
          energy_parameter: draft.energy_parameter,
          activity_level: draft.activity_level,
          auto_target_disabled: draft.auto_target_disabled,
          safety_conditions: draft.safety_conditions,
          effective_from: new Date().toISOString(),
        })).catch(() => undefined)
      }}
    >
      <div className="profile-field-grid">
        <label>
          <span>{t('profile.age')}</span>
          <input
            required
            type="number"
            min={18}
            max={100}
            disabled={saving}
            value={draft.age}
            onChange={(event) => setDraft((current) => ({ ...current, age: Number(event.target.value) }))}
          />
        </label>
        {unitSystem === 'metric' ? (
          <label>
            <span>{t('profile.heightCm')}</span>
            <input
              required
              type="number"
              min={120}
              max={230}
              step="0.1"
              disabled={saving}
              value={draft.height_cm}
              onChange={(event) => setDraft((current) => ({ ...current, height_cm: Number(event.target.value) }))}
            />
          </label>
        ) : (
          <div className="profile-imperial-height">
            <label>
              <span>{t('profile.heightFt')}</span>
              <input
                required
                type="number"
                min={3}
                max={7}
                disabled={saving}
                value={height.feet}
                onChange={(event) => {
                  setValidationError(null)
                  setDraft((current) => ({
                    ...current,
                    height_cm: feetInchesToCm(Number(event.target.value), height.inches),
                  }))
                }}
              />
            </label>
            <label>
              <span>{t('profile.heightIn')}</span>
              <input
                required
                type="number"
                min={0}
                max={11.9}
                step="0.1"
                disabled={saving}
                value={height.inches}
                onChange={(event) => {
                  setValidationError(null)
                  setDraft((current) => ({
                    ...current,
                    height_cm: feetInchesToCm(height.feet, Number(event.target.value)),
                  }))
                }}
              />
            </label>
          </div>
        )}
        <label>
          <span>{t('profile.weight', { unit })}</span>
          <input
            required
            type="number"
            min={weightMin}
            max={weightMax}
            step="0.1"
            disabled={saving}
            value={displayWeight(draft.weight_kg, unitSystem)}
            onChange={(event) => setDraft((current) => ({
              ...current,
              weight_kg: metricWeight(Number(event.target.value), unitSystem),
            }))}
          />
        </label>
        <label>
          <span>{t('profile.energyParameter')}</span>
          <select
            value={draft.energy_parameter}
            disabled={saving}
            onChange={(event) => setDraft((current) => ({
              ...current,
              energy_parameter: event.target.value as ProfileVersion['energy_parameter'],
            }))}
          >
            <option value="female">{t('profile.female')}</option>
            <option value="neutral">{t('profile.neutral')}</option>
            <option value="male">{t('profile.male')}</option>
          </select>
        </label>
        <label>
          <span>{t('profile.activityLevel')}</span>
          <select
            value={draft.activity_level}
            disabled={saving}
            onChange={(event) => setDraft((current) => ({
              ...current,
              activity_level: event.target.value as ProfileVersion['activity_level'],
            }))}
          >
            {(['sedentary', 'light', 'moderate', 'high'] as const).map((value) => (
              <option value={value} key={value}>{t(`profile.activity.${value}`)}</option>
            ))}
          </select>
        </label>
        <fieldset className="profile-field-wide profile-safety-options" disabled={saving}>
          <legend>{t('profile.safetyConditions')}</legend>
          <p>{t('profile.safetyConditionsDescription')}</p>
          <div>
            {SAFETY_CONDITIONS.map((condition) => (
              <label key={condition}>
                <input
                  type="checkbox"
                  checked={(draft.safety_conditions ?? []).includes(condition)}
                  onChange={(event) => setDraft((current) => ({
                    ...current,
                    safety_conditions: event.target.checked
                      ? [...(current.safety_conditions ?? []), condition]
                      : (current.safety_conditions ?? []).filter((item) => item !== condition),
                  }))}
                />
                <span>{t(`profile.safetyConditionOptions.${condition}`)}</span>
              </label>
            ))}
          </div>
        </fieldset>
      </div>
      {validationError ? <div className="form-error" role="alert">{validationError}</div> : null}
      <label className="profile-checkbox">
        <input
          type="checkbox"
          checked={draft.auto_target_disabled}
          disabled={saving}
          onChange={(event) => setDraft((current) => ({
            ...current,
            auto_target_disabled: event.target.checked,
          }))}
        />
        <span>{t('profile.disableAutomaticTargets')}</span>
      </label>
      <div className="profile-form-actions">
        <button className="primary-button" type="submit" disabled={saving}>
          {saving ? t('common.saving') : t('profile.saveBodyProfile')}
        </button>
      </div>
    </form>
  )
}
