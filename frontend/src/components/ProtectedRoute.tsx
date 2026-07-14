import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { useAuth } from '../hooks/useAuth'
import { LoadingState } from './LoadingState'

export function ProtectedRoute() {
  const { user, initializing } = useAuth()
  const location = useLocation()
  const { t } = useTranslation()

  if (initializing) {
    return <LoadingState label={t('common.loadingSession')} />
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <Outlet />
}
