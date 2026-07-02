import type { UserProfile } from '../types'

interface ProfileFormProps {
  profile: UserProfile
  saving: boolean
  onChange: (profile: UserProfile) => void
  onSave: (profile: UserProfile) => Promise<void>
}

export function ProfileForm({ profile, saving, onChange, onSave }: ProfileFormProps) {
  function set<K extends keyof UserProfile>(key: K, value: UserProfile[K]) {
    onChange({ ...profile, [key]: value })
  }

  function setList(key: 'diet_preferences' | 'allergies_or_restrictions', value: string) {
    set(
      key,
      value
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
    )
  }

  return (
    <form className="form-grid" onSubmit={(event) => { event.preventDefault(); void onSave(profile) }}>
      <label>Height cm<input type="number" value={profile.height_cm} onChange={(event) => set('height_cm', Number(event.target.value))} /></label>
      <label>Weight kg<input type="number" value={profile.weight_kg} onChange={(event) => set('weight_kg', Number(event.target.value))} /></label>
      <label>Age<input type="number" value={profile.age} onChange={(event) => set('age', Number(event.target.value))} /></label>
      <label>Gender<select value={profile.gender} onChange={(event) => set('gender', event.target.value as UserProfile['gender'])}><option value="male">Male</option><option value="female">Female</option><option value="other">Other</option></select></label>
      <label>Goal<select value={profile.goal} onChange={(event) => set('goal', event.target.value as UserProfile['goal'])}><option value="fat_loss">Fat loss</option><option value="muscle_gain">Muscle gain</option><option value="maintenance">Maintenance</option></select></label>
      <label>Weekly training<input type="number" value={profile.weekly_training_frequency} onChange={(event) => set('weekly_training_frequency', Number(event.target.value))} /></label>
      <label>Target weight<input type="number" value={profile.target_weight_kg} onChange={(event) => set('target_weight_kg', Number(event.target.value))} /></label>
      <label>Daily calories<input type="number" value={profile.daily_calorie_target} onChange={(event) => set('daily_calorie_target', Number(event.target.value))} /></label>
      <label>Daily protein<input type="number" value={profile.daily_protein_target} onChange={(event) => set('daily_protein_target', Number(event.target.value))} /></label>
      <label className="wide">Diet preferences<input value={profile.diet_preferences.join(', ')} onChange={(event) => setList('diet_preferences', event.target.value)} /></label>
      <label className="wide">Restrictions<input value={profile.allergies_or_restrictions.join(', ')} onChange={(event) => setList('allergies_or_restrictions', event.target.value)} /></label>
      <button className="primary-button" type="submit" disabled={saving}>{saving ? 'Saving...' : 'Save profile'}</button>
    </form>
  )
}
