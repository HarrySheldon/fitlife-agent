import { cmToFeetInches, displayWeight, feetInchesToCm, metricWeight, weightUnit } from '../domain/units'
import { useTranslation } from 'react-i18next'
import type { UnitSystem, UserProfile } from '../types'

interface ProfileFormProps {
  profile: UserProfile
  saving: boolean
  onChange: (profile: UserProfile) => void
  onSave: (profile: UserProfile) => Promise<void>
  unitSystem?: UnitSystem
}

export function ProfileForm({ profile, saving, onChange, onSave, unitSystem = 'metric' }: ProfileFormProps) {
  const { t } = useTranslation()
  function set<K extends keyof UserProfile>(key: K, value: UserProfile[K]) {
    onChange({ ...profile, [key]: value })
  }

  function setList(key: 'allergies_or_restrictions', value: string) {
    set(
      key,
      value
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
    )
  }

  const height = cmToFeetInches(profile.height_cm)
  const unit = weightUnit(unitSystem)

  return (
    <form className="form-grid" onSubmit={(event) => { event.preventDefault(); void onSave(profile) }}>
      {unitSystem === 'metric' ? (
        <label>{t('profile.heightCm')}<input type="number" value={profile.height_cm} onChange={(event) => set('height_cm', Number(event.target.value))} /></label>
      ) : (
        <div className="height-imperial">
          <label>{t('profile.heightFt')}<input type="number" value={height.feet} onChange={(event) => set('height_cm', feetInchesToCm(Number(event.target.value), height.inches))} /></label>
          <label>{t('profile.heightIn')}<input type="number" step="0.1" value={height.inches} onChange={(event) => set('height_cm', feetInchesToCm(height.feet, Number(event.target.value)))} /></label>
        </div>
      )}
      <label>{t('profile.weight', { unit })}<input type="number" step="0.1" value={displayWeight(profile.weight_kg, unitSystem)} onChange={(event) => set('weight_kg', metricWeight(Number(event.target.value), unitSystem))} /></label>
      <label>{t('profile.age')}<input type="number" value={profile.age} onChange={(event) => set('age', Number(event.target.value))} /></label>
      <label>{t('profile.gender')}<select value={profile.gender} onChange={(event) => set('gender', event.target.value as UserProfile['gender'])}><option value="male">{t('profile.male')}</option><option value="female">{t('profile.female')}</option><option value="other">{t('profile.other')}</option></select></label>
      <label>{t('profile.goal')}<select value={profile.goal} onChange={(event) => set('goal', event.target.value as UserProfile['goal'])}><option value="fat_loss">{t('profile.fatLoss')}</option><option value="muscle_gain">{t('profile.muscleGain')}</option><option value="maintenance">{t('profile.maintenance')}</option></select></label>
      <label>{t('profile.weeklyTraining')}<input type="number" value={profile.weekly_training_frequency} onChange={(event) => set('weekly_training_frequency', Number(event.target.value))} /></label>
      <label>{t('profile.experience')}<select value={profile.experience_level} onChange={(event) => set('experience_level', event.target.value as UserProfile['experience_level'])}><option value="beginner">{t('profile.beginner')}</option><option value="novice">{t('profile.novice')}</option><option value="experienced">{t('profile.experienced')}</option></select></label>
      <label>{t('profile.trainingFocus')}<select value={profile.training_preference} onChange={(event) => set('training_preference', event.target.value as UserProfile['training_preference'])}><option value="strength">{t('profile.strength')}</option><option value="cardio">{t('profile.cardio')}</option><option value="mixed">{t('profile.mixed')}</option></select></label>
      <label>{t('profile.targetMode')}<select value={profile.target_mode} onChange={(event) => set('target_mode', event.target.value as UserProfile['target_mode'])}><option value="suggested">{t('profile.coachSuggested')}</option><option value="manual">{t('profile.manual')}</option></select></label>
      <label>{t('profile.targetWeight', { unit })}<input type="number" step="0.1" value={displayWeight(profile.target_weight_kg, unitSystem)} onChange={(event) => set('target_weight_kg', metricWeight(Number(event.target.value), unitSystem))} /></label>
      <label>{t('profile.dailyCalories')}<input type="number" disabled={profile.target_mode === 'suggested'} value={profile.daily_calorie_target} onChange={(event) => set('daily_calorie_target', Number(event.target.value))} /></label>
      <label>{t('profile.dailyProtein')}<input type="number" disabled={profile.target_mode === 'suggested'} value={profile.daily_protein_target} onChange={(event) => set('daily_protein_target', Number(event.target.value))} /></label>
      <label className="wide">{t('profile.restrictions')}<input value={profile.allergies_or_restrictions.join(', ')} onChange={(event) => setList('allergies_or_restrictions', event.target.value)} /></label>
      <button className="primary-button" type="submit" disabled={saving}>{saving ? t('common.saving') : t('profile.save')}</button>
    </form>
  )
}
