import { Activity, BarChart3, Bot, ClipboardCheck, FileUp, Gauge, UserRound } from 'lucide-react'
import { NavLink } from 'react-router-dom'

const items = [
  { to: '/', label: 'Dashboard', icon: Gauge },
  { to: '/upload', label: 'Upload', icon: FileUp },
  { to: '/profile', label: 'Profile', icon: UserRound },
  { to: '/chat', label: 'Chat', icon: Bot },
  { to: '/report', label: 'Weekly Report', icon: BarChart3 },
  { to: '/plan', label: 'Plan', icon: Activity },
  { to: '/evaluation', label: 'Evaluation', icon: ClipboardCheck },
]

export function Sidebar() {
  return (
    <aside className="sidebar">
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
    </aside>
  )
}
