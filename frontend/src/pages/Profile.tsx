import { ErrorState } from '../components/ErrorState'
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
        <span>User context</span>
        <h1>Profile targets and constraints</h1>
      </header>
      <ProfileForm profile={profile} saving={saving} onChange={setProfile} onSave={save} />
    </div>
  )
}
