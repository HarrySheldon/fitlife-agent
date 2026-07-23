import { Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from '../components/Layout'
import { OnboardingGate } from '../components/OnboardingGate'
import { ProtectedRoute } from '../components/ProtectedRoute'
import { Auth } from '../pages/Auth'
import { Evaluation } from '../pages/Evaluation'
import { Logbook } from '../pages/Logbook'
import { Onboarding } from '../pages/Onboarding'
import { Plan } from '../pages/Plan'
import { Profile } from '../pages/Profile'
import { Review } from '../pages/Review'
import { ChangePassword } from '../pages/settings/ChangePassword'
import { DeleteAccount } from '../pages/settings/DeleteAccount'
import { ModelSettings } from '../pages/settings/ModelSettings'
import { PrivacySettings } from '../pages/settings/PrivacySettings'
import { GeneralSettings } from '../pages/settings/GeneralSettings'
import { SecuritySettings } from '../pages/settings/SecuritySettings'
import { SessionSettings } from '../pages/settings/SessionSettings'
import { SettingsHome } from '../pages/settings/SettingsHome'
import { Today } from '../pages/Today'

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Auth />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/onboarding" element={<Onboarding />} />
        <Route element={<OnboardingGate />}>
          <Route element={<Layout />}>
            <Route path="/" element={<Today />} />
            <Route path="/logbook" element={<Logbook />} />
            <Route path="/review" element={<Review />} />
            <Route path="/plan" element={<Plan />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="/settings" element={<SettingsHome />} />
            <Route path="/settings/general" element={<GeneralSettings />} />
            <Route path="/settings/model" element={<ModelSettings />} />
            <Route path="/settings/security" element={<SecuritySettings />} />
            <Route path="/settings/security/password" element={<ChangePassword />} />
            <Route path="/settings/security/sessions" element={<SessionSettings />} />
            <Route path="/settings/privacy" element={<PrivacySettings />} />
            <Route path="/settings/privacy/delete" element={<DeleteAccount />} />
            <Route path="/records" element={<Navigate to="/logbook" replace />} />
            <Route path="/dashboard" element={<Navigate to="/" replace />} />
            <Route path="/report" element={<Navigate to="/review" replace />} />
            <Route path="/upload" element={<Navigate to="/logbook" replace />} />
            <Route path="/chat" element={<Navigate to="/" replace />} />
            <Route path="/evaluation" element={<Evaluation />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Route>
      </Route>
    </Routes>
  )
}
