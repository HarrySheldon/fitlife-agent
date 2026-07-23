import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { AuthProvider } from '../../hooks/useAuth'
import { PreferencesProvider } from '../../hooks/usePreferences'
import i18n from '../../i18n'
import { AppRoutes } from '../../routes/AppRoutes'
import { api, tokenStorage } from '../../services/api'
import type { AuthSession, AuthenticatedUser } from '../../types'

vi.mock('../../hooks/useProfileSetup', () => ({
  useProfileSetup: () => ({
    setup: { profile: {}, goal: {}, target: {}, setup_complete: true },
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}))

const user: AuthenticatedUser = {
  user_id: 'user-1',
  username: 'account-owner',
  email: null,
  phone: null,
  display_name: 'Account Owner',
}
const originalCreateObjectURL = URL.createObjectURL
const originalRevokeObjectURL = URL.revokeObjectURL

function renderRoute(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AuthProvider>
        <PreferencesProvider>
          <AppRoutes />
        </PreferencesProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

beforeEach(async () => {
  vi.restoreAllMocks()
  window.localStorage.clear()
  window.sessionStorage.clear()
  tokenStorage.set('original-token')
  vi.spyOn(api, 'me').mockResolvedValue(user)
  vi.spyOn(api, 'preferences').mockResolvedValue({ language: 'en-US', unit_system: 'metric', timezone: 'UTC' })
  await i18n.changeLanguage('en-US')
})

afterEach(() => {
  vi.unstubAllGlobals()
  if (originalCreateObjectURL) Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: originalCreateObjectURL })
  else Reflect.deleteProperty(URL, 'createObjectURL')
  if (originalRevokeObjectURL) Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: originalRevokeObjectURL })
  else Reflect.deleteProperty(URL, 'revokeObjectURL')
})

it('exposes security and privacy tasks from the settings home', async () => {
  renderRoute('/settings')

  expect(await screen.findByRole('link', { name: /Security/ })).toHaveAttribute('href', '/settings/security')
  expect(screen.getByRole('link', { name: /Privacy and data/ })).toHaveAttribute('href', '/settings/privacy')
})

it('keeps the security overview navigation-only with dedicated task routes', async () => {
  renderRoute('/settings/security')

  expect(await screen.findByRole('heading', { level: 1, name: 'Security' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Change password/ })).toHaveAttribute('href', '/settings/security/password')
  expect(screen.getByRole('link', { name: /Other sessions/ })).toHaveAttribute('href', '/settings/security/sessions')
  expect(screen.queryByLabelText('Current password')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Revoke other sessions' })).not.toBeInTheDocument()
})

it('changes the password without persisting secrets and adopts the replacement session', async () => {
  const replacementUser = { ...user, display_name: 'Rotated Account Owner' }
  const replacementSession: AuthSession = {
    access_token: 'replacement-token',
    token_type: 'bearer',
    user: replacementUser,
  }
  const changePassword = vi.fn().mockResolvedValue(apiSuccess(replacementSession, 'Password changed.'))
  vi.stubGlobal('fetch', changePassword)
  renderRoute('/settings/security/password')

  const currentPassword = await screen.findByLabelText('Current password')
  const newPassword = screen.getByLabelText('New password')
  const confirmation = screen.getByLabelText('Confirm new password')
  fireEvent.change(currentPassword, { target: { value: 'password123' } })
  fireEvent.change(newPassword, { target: { value: 'replacement123' } })
  fireEvent.change(confirmation, { target: { value: 'replacement123' } })

  expect(storageValues(window.localStorage)).not.toContain('password123')
  expect(storageValues(window.sessionStorage)).not.toContain('password123')
  fireEvent.submit(screen.getByRole('button', { name: 'Change password' }).closest('form')!)

  expect(await screen.findByRole('status')).toHaveTextContent('Password changed')
  expect(changePassword).toHaveBeenCalledWith('/api/account/password/change', expect.objectContaining({
    method: 'POST',
    body: JSON.stringify({ current_password: 'password123', new_password: 'replacement123' }),
  }))
  expect(tokenStorage.get()).toBe('replacement-token')
  expect(screen.getByText('Rotated Account Owner')).toBeInTheDocument()
  expect(currentPassword).toHaveValue('')
  expect(newPassword).toHaveValue('')
  expect(confirmation).toHaveValue('')
  expect(storageValues(window.localStorage)).not.toContain('password123')
  expect(storageValues(window.sessionStorage)).not.toContain('password123')
})

it('discards password values when leaving and returning to the password route', async () => {
  renderRoute('/settings/security/password')

  fireEvent.change(await screen.findByLabelText('Current password'), { target: { value: 'password123' } })
  fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'replacement123' } })
  fireEvent.click(screen.getByRole('link', { name: 'Back' }))
  fireEvent.click(await screen.findByRole('link', { name: /Change password/ }))

  expect(await screen.findByLabelText('Current password')).toHaveValue('')
  expect(screen.getByLabelText('New password')).toHaveValue('')
  expect(storageValues(window.localStorage)).not.toContain('password123')
  expect(storageValues(window.sessionStorage)).not.toContain('password123')
})

it('revokes other sessions on its dedicated route and keeps the replacement session', async () => {
  let resolveRevoke!: (response: Response) => void
  const revokeOtherSessions = vi.fn().mockReturnValue(
    new Promise((resolve) => { resolveRevoke = resolve }),
  )
  vi.stubGlobal('fetch', revokeOtherSessions)
  renderRoute('/settings/security/sessions')

  const revokeButton = await screen.findByRole('button', { name: 'Revoke other sessions' })
  expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
  fireEvent.click(revokeButton)

  expect(screen.getByRole('button', { name: 'Revoking sessions...' })).toBeDisabled()
  resolveRevoke(apiSuccess({ access_token: 'sessions-token', token_type: 'bearer', user }, 'Other sessions revoked.'))

  expect(await screen.findByRole('status')).toHaveTextContent('Other sessions revoked')
  expect(revokeOtherSessions).toHaveBeenCalledWith('/api/account/sessions/revoke-others', expect.objectContaining({ method: 'POST' }))
  expect(tokenStorage.get()).toBe('sessions-token')
})

it('keeps a session task error isolated when navigating to the password task', async () => {
  vi.spyOn(api, 'revokeOtherSessions').mockRejectedValue(new Error('Session revoke failed.'))
  renderRoute('/settings/security/sessions')

  fireEvent.click(await screen.findByRole('button', { name: 'Revoke other sessions' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Session revoke failed.')
  fireEvent.click(screen.getByRole('link', { name: 'Back' }))
  fireEvent.click(await screen.findByRole('link', { name: /Change password/ }))

  expect(await screen.findByRole('heading', { level: 1, name: 'Change password' })).toBeInTheDocument()
  expect(screen.queryByText('Session revoke failed.')).not.toBeInTheDocument()
})

it('downloads the privacy export and keeps deletion on its dedicated route', async () => {
  const archive = new Blob(['zip-data'], { type: 'application/zip' })
  let resolveExport!: (response: Response) => void
  const fetchExport = vi.fn().mockReturnValue(new Promise((resolve) => { resolveExport = resolve }))
  vi.stubGlobal('fetch', fetchExport)
  const createObjectURL = vi.fn(() => 'blob:account-export')
  const revokeObjectURL = vi.fn()
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL })
  let clickedDownload = ''
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    clickedDownload = this.download
  })
  renderRoute('/settings/privacy')

  const exportButton = await screen.findByRole('button', { name: 'Download account export' })
  expect(screen.getByRole('link', { name: /Delete account/ })).toHaveAttribute('href', '/settings/privacy/delete')
  expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
  fireEvent.click(exportButton)
  expect(screen.getByRole('button', { name: 'Preparing export...' })).toBeDisabled()

  resolveExport(new Response(archive, {
    status: 200,
    headers: {
      'Content-Type': 'application/zip',
      'Content-Disposition': 'attachment; filename="account-data-export.zip"',
    },
  }))

  expect(await screen.findByRole('status')).toHaveTextContent('Account export downloaded')
  expect(fetchExport).toHaveBeenCalledWith('/api/account/export', expect.objectContaining({ headers: expect.any(Headers) }))
  const exportHeaders = fetchExport.mock.calls[0][1].headers as Headers
  expect(exportHeaders.get('Authorization')).toBe('Bearer original-token')
  expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob))
  expect(clickedDownload).toBe('account-data-export.zip')
  await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith('blob:account-export'))
})

it('keeps authentication after failed deletion and logs out only after successful DELETE confirmation', async () => {
  let rejectDeletion!: (error: Error) => void
  const deleteAccount = vi.fn()
    .mockReturnValueOnce(new Promise<Response>((_, reject) => { rejectDeletion = reject }))
    .mockResolvedValueOnce(apiSuccess(null, 'Account deleted.'))
  vi.stubGlobal('fetch', deleteAccount)
  renderRoute('/settings/privacy/delete')

  const password = await screen.findByLabelText('Current password')
  const confirmation = screen.getByLabelText('Type DELETE to confirm')
  const submit = screen.getByRole('button', { name: 'Delete account permanently' })
  expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', '/settings/privacy')
  expect(submit).toBeDisabled()

  fireEvent.change(password, { target: { value: 'password123' } })
  fireEvent.change(confirmation, { target: { value: 'delete' } })
  expect(submit).toBeDisabled()
  fireEvent.change(confirmation, { target: { value: 'DELETE' } })
  fireEvent.click(submit)

  expect(screen.getByRole('button', { name: 'Deleting account...' })).toBeDisabled()
  expect(tokenStorage.get()).toBe('original-token')
  rejectDeletion(new Error('The current password is incorrect.'))

  expect(await screen.findByRole('alert')).toHaveTextContent('The current password is incorrect.')
  expect(tokenStorage.get()).toBe('original-token')
  expect(screen.getByText('Account Owner')).toBeInTheDocument()
  expect(password).toHaveValue('password123')
  expect(confirmation).toHaveValue('DELETE')
  expect(storageValues(window.localStorage)).not.toContain('password123')
  expect(storageValues(window.sessionStorage)).not.toContain('password123')

  fireEvent.click(screen.getByRole('button', { name: 'Delete account permanently' }))

  expect(await screen.findByRole('heading', { level: 2, name: 'Create your fitness workspace' })).toBeInTheDocument()
  for (const call of deleteAccount.mock.calls) {
    expect(call[0]).toBe('/api/account')
    expect(call[1]).toEqual(expect.objectContaining({
      method: 'DELETE',
      body: JSON.stringify({ password: 'password123', confirmation: 'DELETE' }),
    }))
  }
  expect(tokenStorage.get()).toBeNull()
})

it.each([
  ['/settings/security', '账号安全'],
  ['/settings/security/password', '更改密码'],
  ['/settings/security/sessions', '其他会话'],
  ['/settings/privacy', '隐私与数据'],
  ['/settings/privacy/delete', '删除账户'],
])('localizes the account settings route %s in Chinese', async (route, heading) => {
  vi.mocked(api.preferences).mockResolvedValue({ language: 'zh-CN', unit_system: 'metric', timezone: 'Asia/Shanghai' })
  await i18n.changeLanguage('zh-CN')

  renderRoute(route)

  expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeInTheDocument()
})

function storageValues(storage: Storage): string {
  return Array.from({ length: storage.length }, (_, index) => storage.getItem(storage.key(index) ?? '') ?? '').join('\n')
}

function apiSuccess<T>(data: T, message = ''): Response {
  return new Response(JSON.stringify({ success: true, data, message }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}
