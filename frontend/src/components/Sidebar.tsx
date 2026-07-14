import { Activity, BarChart3, CalendarCheck, CalendarDays, LogOut, Settings, UserRound } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { useAuth } from '../hooks/useAuth'

const items = [
  { to: '/', labelKey: 'navigation.today', icon: CalendarCheck },
  { to: '/logbook', labelKey: 'navigation.logbook', icon: CalendarDays },
  { to: '/review', labelKey: 'navigation.review', icon: BarChart3 },
  { to: '/plan', labelKey: 'navigation.plan', icon: Activity },
  { to: '/profile', labelKey: 'navigation.profile', icon: UserRound },
  { to: '/settings', labelKey: 'navigation.settings', icon: Settings },
]

export function Sidebar() {
  const { user, logout } = useAuth()
  const { t } = useTranslation()
  const identity = user?.username || user?.email || user?.phone || ''

  return (
    <aside className="sidebar">
      <div className="sidebar-main">
        <div className="brand-block">
          <div className="brand-mark">FL</div>
          <div>
            <h1>FitLife Agent</h1>
            <p>{t('navigation.tagline')}</p>
          </div>
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
        <div>
          <strong>{user?.display_name}</strong>
          <span>{identity}</span>
        </div>
        <button type="button" onClick={logout} aria-label={t('navigation.logout')}>
          <LogOut size={18} />
        </button>
      </div>
    </aside>
  )
}
