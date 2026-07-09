import { Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from '../components/Layout'
import { ProtectedRoute } from '../components/ProtectedRoute'
import { Auth } from '../pages/Auth'
import { Chat } from '../pages/Chat'
import { Dashboard } from '../pages/Dashboard'
import { Evaluation } from '../pages/Evaluation'
import { Plan } from '../pages/Plan'
import { Profile } from '../pages/Profile'
import { Records } from '../pages/Records'
import { WeeklyReport } from '../pages/WeeklyReport'

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Auth />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/records" element={<Records />} />
          <Route path="/upload" element={<Navigate to="/records" replace />} />
          <Route path="/profile" element={<Profile />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/report" element={<WeeklyReport />} />
          <Route path="/plan" element={<Plan />} />
          <Route path="/evaluation" element={<Evaluation />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  )
}
