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

  function setList(key: 'allergies_or_restrictions', value: string) {
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
      <label>Experience<select value={profile.experience_level} onChange={(event) => set('experience_level', event.target.value as UserProfile['experience_level'])}><option value="beginner">Beginner</option><option value="novice">Novice</option><option value="experienced">Experienced</option></select></label>
      <label>Training focus<select value={profile.training_preference} onChange={(event) => set('training_preference', event.target.value as UserProfile['training_preference'])}><option value="strength">Strength</option><option value="cardio">Cardio</option><option value="mixed">Mixed</option></select></label>
      <label>Target mode<select value={profile.target_mode} onChange={(event) => set('target_mode', event.target.value as UserProfile['target_mode'])}><option value="suggested">Coach suggested</option><option value="manual">Manual</option></select></label>
      <label>Target weight<input type="number" value={profile.target_weight_kg} onChange={(event) => set('target_weight_kg', Number(event.target.value))} /></label>
      <label>Daily calories<input type="number" disabled={profile.target_mode === 'suggested'} value={profile.daily_calorie_target} onChange={(event) => set('daily_calorie_target', Number(event.target.value))} /></label>
      <label>Daily protein<input type="number" disabled={profile.target_mode === 'suggested'} value={profile.daily_protein_target} onChange={(event) => set('daily_protein_target', Number(event.target.value))} /></label>
      <label className="wide">Restrictions<input value={profile.allergies_or_restrictions.join(', ')} onChange={(event) => setList('allergies_or_restrictions', event.target.value)} /></label>
      <button className="primary-button" type="submit" disabled={saving}>{saving ? 'Saving...' : 'Save profile'}</button>
    </form>
  )
}
