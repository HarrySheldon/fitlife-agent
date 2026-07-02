import { useEffect, useState } from 'react'

import { api } from '../services/api'
import type { UserProfile } from '../types'

export function useProfile() {
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .profile()
      .then(setProfile)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  async function save(next: UserProfile) {
    setSaving(true)
    setError(null)
    try {
      const saved = await api.saveProfile(next)
      setProfile(saved)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return { profile, setProfile, loading, saving, error, save }
}
