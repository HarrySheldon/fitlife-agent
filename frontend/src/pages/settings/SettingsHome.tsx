import { ChevronRight, Cpu } from 'lucide-react'
import { Link } from 'react-router-dom'

export function SettingsHome() {
  return (
    <div className="page-stack settings-page">
      <header className="page-header">
        <span>Account</span>
        <h1>Settings</h1>
      </header>

      <nav className="settings-list" aria-label="Settings tasks">
        <Link className="settings-row" to="/settings/model">
          <span className="settings-row-icon" aria-hidden="true"><Cpu size={20} /></span>
          <span className="settings-row-copy">
            <strong>Model connection</strong>
            <span>Provider, protocol, model and API key</span>
          </span>
          <ChevronRight size={20} aria-hidden="true" />
        </Link>
      </nav>
    </div>
  )
}
