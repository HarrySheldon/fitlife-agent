import { BrowserRouter } from 'react-router-dom'

import { AuthProvider } from './hooks/useAuth'
import { PreferencesProvider } from './hooks/usePreferences'
import { AppRoutes } from './routes/AppRoutes'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <PreferencesProvider>
          <AppRoutes />
        </PreferencesProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
