import { Navigate, Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { useProfileSetup } from '../hooks/useProfileSetup'


export function OnboardingGate() {
  const { t } = useTranslation()
  const { setup, loading, error, refresh } = useProfileSetup()

  async function retry() {
    try {
      await refresh()
    } catch {
      // The hook owns the visible error state.
    }
  }

  if (loading || (!setup && !error)) {
    return <div className="state-box onboarding-gate-state">{t('onboarding.loading')}...</div>
  }

  if (error) {
    return (
      <div className="state-box error onboarding-gate-state">
        <p>{error}</p>
        <button
          className="secondary-button"
          type="button"
          onClick={() => void retry()}
        >
          {t('common.tryAgain')}
        </button>
      </div>
    )
  }

  if (!setup?.setup_complete) {
    return <Navigate to="/onboarding" replace />
  }

  return <Outlet />
}
