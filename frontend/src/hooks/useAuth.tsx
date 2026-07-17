import type { ReactNode } from 'react'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import { api, tokenStorage } from '../services/api'
import type { AuthRequest, AuthSession, AuthenticatedUser } from '../types'

interface AuthContextValue {
  user: AuthenticatedUser | null
  initializing: boolean
  login: (payload: AuthRequest) => Promise<void>
  register: (payload: AuthRequest) => Promise<void>
  replaceSession: (session: AuthSession) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthenticatedUser | null>(null)
  const [initializing, setInitializing] = useState(true)

  const replaceSession = useCallback((session: AuthSession) => {
    tokenStorage.set(session.access_token)
    setUser(session.user)
  }, [])

  useEffect(() => {
    if (!tokenStorage.get()) {
      setInitializing(false)
      return
    }
    api
      .me()
      .then(setUser)
      .catch(() => tokenStorage.clear())
      .finally(() => setInitializing(false))
  }, [])

  async function login(payload: AuthRequest) {
    const session = await api.login(payload)
    replaceSession(session)
  }

  async function register(payload: AuthRequest) {
    const session = await api.register(payload)
    replaceSession(session)
  }

  function logout() {
    tokenStorage.clear()
    setUser(null)
  }

  const value = useMemo(
    () => ({ user, initializing, login, register, replaceSession, logout }),
    [user, initializing, replaceSession],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return value
}
