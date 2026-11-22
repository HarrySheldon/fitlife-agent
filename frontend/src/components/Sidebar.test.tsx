import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import { Sidebar } from './Sidebar'

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

describe('Sidebar navigation hierarchy', () => {
  beforeEach(async () => {
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
})
