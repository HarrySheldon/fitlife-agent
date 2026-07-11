import { Activity, BarChart3, CalendarCheck, CalendarDays, LogOut, UserRound } from 'lucide-react'
import { NavLink } from 'react-router-dom'

import { useAuth } from '../hooks/useAuth'

const items = [
  { to: '/', label: 'Today', icon: CalendarCheck },
  { to: '/logbook', label: 'Logbook', icon: CalendarDays },
  { to: '/review', label: 'Review', icon: BarChart3 },
  { to: '/plan', label: 'Plan', icon: Activity },
  { to: '/profile', label: 'Profile', icon: UserRound },
]

export function Sidebar() {
  const { user, logout } = useAuth()
  const identity = user?.username || user?.email || user?.phone || ''

  return (
    <aside className="sidebar">
      <div className="sidebar-main">
        <div className="brand-block">
          <div className="brand-mark">FL</div>
          <div>
            <h1>FitLife Agent</h1>
            <p>Daily fitness log</p>
          </div>
        </div>
        <nav>
          {items.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <Icon size={18} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </div>
      <div className="sidebar-user">
        <div>
          <strong>{user?.display_name}</strong>
          <span>{identity}</span>
        </div>
        <button type="button" onClick={logout} aria-label="Log out">
          <LogOut size={18} />
        </button>
      </div>
    </aside>
  )
}
