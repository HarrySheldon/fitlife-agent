import { act, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import { notifyModelWorkspaceChanged } from '../lib/modelStatusEvents'
import { Sidebar } from './Sidebar'

const mocks = vi.hoisted(() => ({
  modelWorkspace: vi.fn(),
}))

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({
    user: {
      user_id: 'user-1',
      username: 'root',
      email: null,
      phone: null,
      display_name: 'Harry',
    },
    logout: vi.fn(),
  }),
}))

vi.mock('../services/api', () => ({
  api: {
    modelWorkspace: mocks.modelWorkspace,
  },
}))

describe('Sidebar navigation hierarchy', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    mocks.modelWorkspace.mockResolvedValue({ revision: 0, active: null, draft: null })
    await i18n.changeLanguage('en-US')
  })

  it('keeps the 4 core workflow links in nav, places Settings as a header icon, and links footer user card to /profile', async () => {
    const { unmount } = render(
      <MemoryRouter initialEntries={['/coach']}>
        <Sidebar />
      </MemoryRouter>,
    )

    const nav = screen.getByRole('navigation')
    const navLinks = within(nav).getAllByRole('link')
    expect(navLinks.map((link) => link.getAttribute('href'))).toEqual([
      '/',
      '/plan',
      '/progress',
      '/coach',
    ])

    const settingsLink = screen.getByRole('link', { name: 'Settings' })
    expect(settingsLink).toHaveAttribute('href', '/settings')
    expect(nav).not.toContainElement(settingsLink)

    const profileLink = screen.getByRole('link', { name: 'Profile & Goals' })
    expect(profileLink).toHaveAttribute('href', '/profile')
    expect(profileLink).toHaveTextContent('Harry')
    expect(profileLink).toHaveTextContent('H')
    expect(nav).not.toContainElement(profileLink)

    unmount()
    await i18n.changeLanguage('zh-CN')
    render(
      <MemoryRouter initialEntries={['/profile']}>
        <Sidebar />
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: '设置' })).toHaveAttribute('href', '/settings')
    const zhProfileLink = screen.getByRole('link', { name: '档案与目标' })
    expect(zhProfileLink).toHaveAttribute('href', '/profile')
    expect(zhProfileLink).toHaveClass('active')
  })

  it('shows subtle status dot when no active model is enabled and updates dynamically on workspace events', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Sidebar />
      </MemoryRouter>,
    )

    const settingsLink = screen.getByRole('link', { name: 'Settings' })
    await waitFor(() => expect(settingsLink).toHaveAttribute('data-model-configured', 'false'))
    expect(settingsLink.querySelector('.sidebar-status-dot')).toBeInTheDocument()
    expect(settingsLink).toHaveAttribute('title', 'Settings — AI model not configured')

    act(() => {
      notifyModelWorkspaceChanged(true)
    })
    expect(settingsLink).toHaveAttribute('data-model-configured', 'true')
    expect(settingsLink.querySelector('.sidebar-status-dot')).not.toBeInTheDocument()
    expect(settingsLink).toHaveAttribute('title', 'Settings')

    act(() => {
      notifyModelWorkspaceChanged(false)
    })
    expect(settingsLink).toHaveAttribute('data-model-configured', 'false')
    expect(settingsLink.querySelector('.sidebar-status-dot')).toBeInTheDocument()
  })

  it('does not render status dot when an active enabled model workspace is present on initial load', async () => {
    mocks.modelWorkspace.mockResolvedValue({
      revision: 1,
      active: { enabled: true, api_key_configured: true },
      draft: null,
    })

    render(
      <MemoryRouter initialEntries={['/']}>
        <Sidebar />
      </MemoryRouter>,
    )

    const settingsLink = screen.getByRole('link', { name: 'Settings' })
    await waitFor(() => expect(settingsLink).toHaveAttribute('data-model-configured', 'true'))
    expect(settingsLink.querySelector('.sidebar-status-dot')).not.toBeInTheDocument()
  })
})
