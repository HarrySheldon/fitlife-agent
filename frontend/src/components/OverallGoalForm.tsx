import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { OverallGoal, OverallGoalVersion, OverallGoalVersionUpdate } from '../types'


interface OverallGoalFormProps {
  goal: OverallGoalVersion
  saving: boolean
  onSave: (goal: OverallGoalVersionUpdate) => Promise<unknown>
}

export function OverallGoalForm({ goal, saving, onSave }: OverallGoalFormProps) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState<OverallGoal>(goal.goal)

  useEffect(() => setDraft(goal.goal), [goal.id])

  return (
    <form
      className="profile-form"
      onSubmit={(event) => {
        event.preventDefault()
        void Promise.resolve(onSave({
          goal: draft,
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
      <div className="profile-form-actions">
        <button className="primary-button" type="submit" disabled={saving}>
          {saving ? t('common.saving') : t('profile.saveOverallGoal')}
        </button>
      </div>
    </form>
  )
}
