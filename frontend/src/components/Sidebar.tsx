import { Activity, BarChart3, Bot, CalendarDays, ClipboardCheck, Gauge, LogOut, UserRound } from 'lucide-react'
import { NavLink } from 'react-router-dom'

import { useAuth } from '../hooks/useAuth'

const items = [
  { to: '/', label: 'Dashboard', icon: Gauge },
  { to: '/records', label: 'Records', icon: CalendarDays },
  { to: '/profile', label: 'Profile', icon: UserRound },
  { to: '/chat', label: 'Chat', icon: Bot },
  { to: '/report', label: 'Weekly Report', icon: BarChart3 },
  { to: '/plan', label: 'Plan', icon: Activity },
  { to: '/evaluation', label: 'Evaluation', icon: ClipboardCheck },
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
            <p>Agentic RAG Coach</p>
          </div>
        </div>
        <nav>
          {items.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
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
