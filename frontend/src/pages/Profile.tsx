import { ErrorState } from '../components/ErrorState'
import { CoachPanel } from '../components/CoachPanel'
import { LoadingState } from '../components/LoadingState'
import { ProfileForm } from '../components/ProfileForm'
import { useProfile } from '../hooks/useProfile'

export function Profile() {
  const { profile, setProfile, loading, saving, error, save } = useProfile()
  if (loading) return <LoadingState label="Loading profile" />
  if (error) return <ErrorState message={error} />
  if (!profile) return null

  return (
    <div className="page-stack">
      <header className="page-header">
        <span>Personalization</span>
        <h1>Profile</h1>
      </header>
      <div className="profile-layout">
        <ProfileForm profile={profile} saving={saving} onChange={setProfile} onSave={save} />
        <CoachPanel surface="profile" actions={[{ action: 'suggest_targets', label: 'Analyze my targets' }]} />
      </div>
    </div>
  )
}
