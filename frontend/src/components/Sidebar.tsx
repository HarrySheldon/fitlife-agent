import { Activity, BarChart3, Bot, CalendarCheck, LogOut, Settings, UserRound } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { useAuth } from '../hooks/useAuth'
import { MODEL_WORKSPACE_CHANGED_EVENT, type ModelWorkspaceChangedDetail } from '../lib/modelStatusEvents'
import { api } from '../services/api'

const items = [
  { to: '/', labelKey: 'navigation.today', icon: CalendarCheck },
  { to: '/plan', labelKey: 'navigation.plan', icon: Activity },
  { to: '/progress', labelKey: 'navigation.progress', icon: BarChart3 },
  { to: '/coach', labelKey: 'navigation.coach', icon: Bot },
]

export function Sidebar() {
  const { user, logout } = useAuth()
  const { t } = useTranslation()
  const [modelConfigured, setModelConfigured] = useState<boolean | null>(null)
  const identity = user?.username || user?.email || user?.phone || ''
  const displayName = user?.display_name || identity
  const trimmedName = displayName.trim()
  const avatarInitial = trimmedName ? Array.from(trimmedName)[0].toUpperCase() : ''

  useEffect(() => {
    const handleWorkspaceChanged = (event: Event) => {
      const detail = (event as CustomEvent<ModelWorkspaceChangedDetail>).detail
      if (detail && typeof detail.configured === 'boolean') {
        setModelConfigured(detail.configured)
      }
    }
    window.addEventListener(MODEL_WORKSPACE_CHANGED_EVENT, handleWorkspaceChanged)
    return () => {
      window.removeEventListener(MODEL_WORKSPACE_CHANGED_EVENT, handleWorkspaceChanged)
    }
  }, [])

  useEffect(() => {
    if (!user?.user_id || typeof api?.modelWorkspace !== 'function') {
      setModelConfigured(null)
      return
    }
    let active = true
    Promise.resolve(api.modelWorkspace())
      .then((workspace) => {
        if (!active || !workspace) return
        setModelConfigured(Boolean(workspace.active?.enabled && workspace.active?.api_key_configured))
      })
      .catch(() => {
        // Keep unknown status if workspace check is unavailable.
      })
    return () => {
      active = false
    }
  }, [user?.user_id])

  const settingsTitle = modelConfigured === false
    ? `${t('navigation.settings')} — ${t('navigation.modelNotConfiguredHint')}`
    : t('navigation.settings')

  return (
    <aside className="sidebar">
      <div className="sidebar-main">
        <div className="sidebar-header">
          <div className="brand-block">
            <div className="brand-mark">FL</div>
            <div>
              <h1>FitLife Agent</h1>
              <p>{t('navigation.tagline')}</p>
            </div>
          </div>
          <NavLink
            to="/settings"
            aria-label={t('navigation.settings')}
            title={settingsTitle}
            data-model-configured={modelConfigured === null ? 'unknown' : String(modelConfigured)}
            className={({ isActive }) => `sidebar-icon-link ${isActive ? 'active' : ''}`}
          >
            <Settings size={18} aria-hidden="true" />
            {modelConfigured === false ? <span className="sidebar-status-dot" aria-hidden="true" /> : null}
          </NavLink>
        </div>
        <nav>
          {items.map(({ to, labelKey, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <Icon size={18} />
              <span>{t(labelKey)}</span>
            </NavLink>
          ))}
        </nav>
      </div>
      <div className="sidebar-user">
        <NavLink
          to="/profile"
          aria-label={t('navigation.profile')}
          title={t('navigation.profile')}
          className={({ isActive }) => `sidebar-profile-link ${isActive ? 'active' : ''}`}
        >
          <span className="sidebar-avatar" aria-hidden="true">
            {avatarInitial || <UserRound size={16} />}
          </span>
          <span className="sidebar-profile-copy">
            <strong>{displayName}</strong>
            <span>{t('navigation.profile')}</span>
          </span>
        </NavLink>
        <button
          type="button"
          onClick={() => logout()}
          aria-label={t('navigation.logout')}
          title={t('navigation.logout')}
        >
          <LogOut size={17} aria-hidden="true" />
        </button>
      </div>
    </aside>
  )
}
