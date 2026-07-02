import { Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from '../components/Layout'
import { Chat } from '../pages/Chat'
import { Dashboard } from '../pages/Dashboard'
import { Evaluation } from '../pages/Evaluation'
import { Plan } from '../pages/Plan'
import { Profile } from '../pages/Profile'
import { Upload } from '../pages/Upload'
import { WeeklyReport } from '../pages/WeeklyReport'

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/upload" element={<Upload />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/report" element={<WeeklyReport />} />
        <Route path="/plan" element={<Plan />} />
        <Route path="/evaluation" element={<Evaluation />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
