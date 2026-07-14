import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../services/api'
import { PreferencesProvider, usePreferences } from './usePreferences'


const state = vi.hoisted(() => ({
  user: null as null | { user_id: string; username: string; email: null; phone: null; display_name: string },
}))

vi.mock('./useAuth', () => ({
  useAuth: () => ({ user: state.user }),
}))

vi.mock('../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/api')>()
  return {
    ...original,
    api: {
      ...original.api,
      preferences: vi.fn(),
      updatePreferences: vi.fn(),
    },
  }
})

function Probe() {
  const { preferences, loading, updatePreferences, localDate } = usePreferences()
  return (
    <div>
      <span data-testid="language">{preferences.language}</span>
      <span data-testid="unit">{preferences.unit_system}</span>
      <span data-testid="timezone">{preferences.timezone}</span>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="date">{localDate(new Date('2026-07-13T00:30:00Z'))}</span>
      <button type="button" onClick={() => void updatePreferences({ language: 'zh-CN' })}>Chinese</button>
    </div>
  )
}

function renderProvider(children: ReactNode = <Probe />) {
  return render(<PreferencesProvider>{children}</PreferencesProvider>)
}

describe('PreferencesProvider', () => {
  beforeEach(() => {
    window.localStorage.clear()
    state.user = null
    vi.mocked(api.preferences).mockReset()
    vi.mocked(api.updatePreferences).mockReset()
  })

  it('uses cached language before login', async () => {
    window.localStorage.setItem('fitlife_language', 'zh-CN')

    renderProvider()

    expect(screen.getByTestId('language')).toHaveTextContent('zh-CN')
    await waitFor(() => expect(document.documentElement.lang).toBe('zh-CN'))
    expect(api.preferences).not.toHaveBeenCalled()
  })

  it('loads account preferences and computes dates in the account timezone', async () => {
    state.user = { user_id: 'user-a', username: 'user-a', email: null, phone: null, display_name: 'User A' }
    vi.mocked(api.preferences).mockResolvedValue({
      language: 'en-US',
      unit_system: 'imperial',
      timezone: 'America/Los_Angeles',
    })

    renderProvider()

    await waitFor(() => expect(screen.getByTestId('unit')).toHaveTextContent('imperial'))
    expect(screen.getByTestId('date')).toHaveTextContent('2026-07-12')
    expect(window.localStorage.getItem('fitlife_language')).toBe('en-US')
  })

  it('applies language immediately and persists the server result', async () => {
    state.user = { user_id: 'user-a', username: 'user-a', email: null, phone: null, display_name: 'User A' }
    vi.mocked(api.preferences).mockResolvedValue({ language: 'en-US', unit_system: 'metric', timezone: 'UTC' })
    vi.mocked(api.updatePreferences).mockResolvedValue({ language: 'zh-CN', unit_system: 'metric', timezone: 'UTC' })
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'))

    fireEvent.click(screen.getByRole('button', { name: 'Chinese' }))

    expect(screen.getByTestId('language')).toHaveTextContent('zh-CN')
    await waitFor(() => expect(api.updatePreferences).toHaveBeenCalledWith({ language: 'zh-CN' }))
    await waitFor(() => expect(document.documentElement.lang).toBe('zh-CN'))
  })
})

