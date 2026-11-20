import { Suspense, lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from '../components/Layout'
import { LoadingState } from '../components/LoadingState'
import { OnboardingGate } from '../components/OnboardingGate'
import { ProtectedRoute } from '../components/ProtectedRoute'
import { Auth } from '../pages/Auth'
import { Today } from '../pages/Today'

const CoachPage = lazy(() => import('../pages/CoachPage').then((m) => ({ default: m.CoachPage })))
const Evaluation = lazy(() => import('../pages/Evaluation').then((m) => ({ default: m.Evaluation })))
const Logbook = lazy(() => import('../pages/Logbook').then((m) => ({ default: m.Logbook })))
const LogbookImport = lazy(() => import('../pages/Logbook').then((m) => ({ default: m.LogbookImport })))
const LogbookDay = lazy(() => import('../pages/logbook/LogbookDay').then((m) => ({ default: m.LogbookDay })))
const MealEntry = lazy(() => import('../pages/MealEntry').then((m) => ({ default: m.MealEntry })))
const Onboarding = lazy(() => import('../pages/Onboarding').then((m) => ({ default: m.Onboarding })))
const Plan = lazy(() => import('../pages/Plan').then((m) => ({ default: m.Plan })))
const NewPlan = lazy(() => import('../pages/plan/NewPlan').then((m) => ({ default: m.NewPlan })))
const PlanDetail = lazy(() => import('../pages/plan/PlanDetail').then((m) => ({ default: m.PlanDetail })))
const Profile = lazy(() => import('../pages/Profile').then((m) => ({ default: m.Profile })))
const Progress = lazy(() => import('../pages/Progress').then((m) => ({ default: m.Progress })))
const EditProfile = lazy(() => import('../pages/profile/EditProfile').then((m) => ({ default: m.EditProfile })))
const WeeklyReview = lazy(() => import('../pages/review/WeeklyReview').then((m) => ({ default: m.WeeklyReview })))
const ChangePassword = lazy(() => import('../pages/settings/ChangePassword').then((m) => ({ default: m.ChangePassword })))
const DeleteAccount = lazy(() => import('../pages/settings/DeleteAccount').then((m) => ({ default: m.DeleteAccount })))
const ModelSettings = lazy(() => import('../pages/settings/ModelSettings').then((m) => ({ default: m.ModelSettings })))
const PrivacySettings = lazy(() => import('../pages/settings/PrivacySettings').then((m) => ({ default: m.PrivacySettings })))
const GeneralSettings = lazy(() => import('../pages/settings/GeneralSettings').then((m) => ({ default: m.GeneralSettings })))
const SecuritySettings = lazy(() => import('../pages/settings/SecuritySettings').then((m) => ({ default: m.SecuritySettings })))
const SessionSettings = lazy(() => import('../pages/settings/SessionSettings').then((m) => ({ default: m.SessionSettings })))
const SettingsHome = lazy(() => import('../pages/settings/SettingsHome').then((m) => ({ default: m.SettingsHome })))
const SmartEntry = lazy(() => import('../pages/SmartEntry').then((m) => ({ default: m.SmartEntry })))
const WorkoutEntry = lazy(() => import('../pages/WorkoutEntry').then((m) => ({ default: m.WorkoutEntry })))

export function AppRoutes() {
  return (
    <Suspense fallback={<LoadingState label="Loading" />}>
      <Routes>
        <Route path="/login" element={<Auth />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/onboarding" element={<Onboarding />} />
          <Route element={<OnboardingGate />}>
            <Route element={<Layout />}>
              <Route path="/" element={<Today />} />
              <Route path="/today/meal/new" element={<MealEntry />} />
              <Route path="/today/workout/new" element={<WorkoutEntry />} />
              <Route path="/today/smart-entry" element={<SmartEntry />} />
              <Route path="/logbook" element={<Logbook />} />
              <Route path="/logbook/import" element={<LogbookImport />} />
              <Route path="/logbook/:date" element={<LogbookDay />} />
              <Route path="/progress" element={<Progress />} />
              <Route path="/progress/week/:week" element={<WeeklyReview />} />
              <Route path="/review" element={<Navigate to="/progress" replace />} />
              <Route path="/review/week/:week" element={<WeeklyReview />} />
              <Route path="/plan" element={<Plan />} />
              <Route path="/plan/new" element={<NewPlan />} />
              <Route path="/plan/:planId" element={<PlanDetail />} />
              <Route path="/coach" element={<CoachPage />} />
              <Route path="/profile" element={<Profile />} />
              <Route path="/profile/edit" element={<EditProfile />} />
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
              <Route path="/report" element={<Navigate to="/progress" replace />} />
              <Route path="/upload" element={<Navigate to="/logbook/import" replace />} />
              <Route path="/chat" element={<Navigate to="/coach" replace />} />
              <Route path="/evaluation" element={<Evaluation />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Route>
        </Route>
      </Routes>
    </Suspense>
  )
}
