import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import { AuthProvider } from './hooks/useAuth'
import { PreferencesProvider } from './hooks/usePreferences'
import { AppRoutes } from './routes/AppRoutes'

const router = createBrowserRouter([{
  path: '*',
  element: (
      <AuthProvider>
        <PreferencesProvider>
          <AppRoutes />
        </PreferencesProvider>
      </AuthProvider>
  ),
}])

export default function App() {
  return <RouterProvider router={router} />
}
