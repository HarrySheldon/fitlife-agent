import { Outlet } from 'react-router-dom'

import { Sidebar } from './Sidebar'
import { CoachProvider } from '../hooks/useCoach'
import { useAuth } from '../hooks/useAuth'
import { CoachWindow } from './coach/CoachWindow'

export function Layout() {
  if (import.meta.env.VITE_COACH_CONVERSATIONS_ENABLED === 'true') return <CoachLayout />
  return <LayoutContent />
}

function CoachLayout() {
  const { user } = useAuth()
  if (!user) return <LayoutContent />
  return <CoachProvider key={user.user_id} owner={user.user_id}><LayoutContent /><CoachWindow /></CoachProvider>
}

function LayoutContent() {
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main-panel">
        <Outlet />
      </main>
    </div>
  )
}
