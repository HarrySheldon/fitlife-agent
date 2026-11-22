import { Activity, BarChart3, Bot, CalendarCheck, LogOut, Settings, UserRound } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { useAuth } from '../hooks/useAuth'

const items = [
  { to: '/', labelKey: 'navigation.today', icon: CalendarCheck },
  { to: '/plan', labelKey: 'navigation.plan', icon: Activity },
  { to: '/progress', labelKey: 'navigation.progress', icon: BarChart3 },
  { to: '/coach', labelKey: 'navigation.coach', icon: Bot },
]

export function Sidebar() {
  const { user, logout } = useAuth()
  const { t } = useTranslation()
  const identity = user?.username || user?.email || user?.phone || ''
  const displayName = user?.display_name || identity
  const trimmedName = displayName.trim()
  const avatarInitial = trimmedName ? Array.from(trimmedName)[0].toUpperCase() : ''

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
            title={t('navigation.settings')}
            className={({ isActive }) => `sidebar-icon-link ${isActive ? 'active' : ''}`}
          >
            <Settings size={18} aria-hidden="true" />
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
