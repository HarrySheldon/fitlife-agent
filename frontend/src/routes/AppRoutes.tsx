import { Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from '../components/Layout'
import { ProtectedRoute } from '../components/ProtectedRoute'
import { Auth } from '../pages/Auth'
import { Evaluation } from '../pages/Evaluation'
import { Logbook } from '../pages/Logbook'
import { Plan } from '../pages/Plan'
import { Profile } from '../pages/Profile'
import { Review } from '../pages/Review'
import { Today } from '../pages/Today'

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Auth />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route path="/" element={<Today />} />
          <Route path="/logbook" element={<Logbook />} />
          <Route path="/review" element={<Review />} />
          <Route path="/plan" element={<Plan />} />
          <Route path="/profile" element={<Profile />} />
          <Route path="/records" element={<Navigate to="/logbook" replace />} />
          <Route path="/dashboard" element={<Navigate to="/" replace />} />
          <Route path="/report" element={<Navigate to="/review" replace />} />
          <Route path="/upload" element={<Navigate to="/logbook" replace />} />
          <Route path="/chat" element={<Navigate to="/" replace />} />
          <Route path="/evaluation" element={<Evaluation />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  )
}
