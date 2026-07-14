import { ErrorState } from '../components/ErrorState'
import { CoachPanel } from '../components/CoachPanel'
import { LoadingState } from '../components/LoadingState'
import { ProfileForm } from '../components/ProfileForm'
import { useProfile } from '../hooks/useProfile'
import { usePreferences } from '../hooks/usePreferences'
import { useTranslation } from 'react-i18next'

export function Profile() {
  const { t } = useTranslation()
  const { preferences } = usePreferences()
  const { profile, setProfile, loading, saving, error, save } = useProfile()
  if (loading) return <LoadingState label={t('profile.loading')} />
  if (error) return <ErrorState message={error} />
  if (!profile) return null

  return (
    <div className="page-stack">
      <header className="page-header">
        <span>{t('profile.eyebrow')}</span>
        <h1>{t('profile.title')}</h1>
      </header>
      <div className="profile-layout">
        <ProfileForm profile={profile} unitSystem={preferences.unit_system} saving={saving} onChange={setProfile} onSave={save} />
        <CoachPanel surface="profile" actions={[{ action: 'suggest_targets', label: t('profile.analyzeTargets') }]} />
      </div>
    </div>
  )
}
