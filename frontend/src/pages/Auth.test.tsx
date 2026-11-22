import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import { api, languageStorage } from '../services/api'
import { Auth } from './Auth'

const authMocks = vi.hoisted(() => ({
  login: vi.fn(),
  register: vi.fn(),
}))

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({
    user: null,
    initializing: false,
    login: authMocks.login,
    register: authMocks.register,
    logout: vi.fn(),
  }),
}))

beforeEach(async () => {
  vi.restoreAllMocks()
  window.localStorage.clear()
  authMocks.login.mockReset().mockResolvedValue(undefined)
  authMocks.register.mockReset().mockResolvedValue(undefined)
  await i18n.changeLanguage('zh-CN')
})

describe('Auth UX-3', () => {
  it('defaults to register on zero-user local install and validates password confirmation + optional display name', async () => {
    vi.spyOn(api, 'authStatus').mockResolvedValue({ has_users: false })
    render(<MemoryRouter><Auth /></MemoryRouter>)

    // Zero users -> switches to initialization registration view
    expect(await screen.findByRole('heading', { level: 2, name: '初始化你的本地健身空间' })).toBeInTheDocument()
    expect(screen.getByText('数据与密钥仅保存在本机')).toBeInTheDocument()
    // No email/phone/username picker tabs and no fake preview cards
    expect(screen.queryByRole('group', { name: '注册标识类型' })).not.toBeInTheDocument()
    expect(screen.queryByText(/午餐牛肉饭/)).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/用户名/), { target: { value: 'harry' } })
    fireEvent.change(screen.getByLabelText(/^密码/), { target: { value: 'password123' } })
    fireEvent.change(screen.getByLabelText(/确认密码/), { target: { value: 'password999' } })
    fireEvent.click(screen.getByRole('button', { name: /创建账号并开始/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('两次输入的密码不一致')
    expect(authMocks.register).not.toHaveBeenCalled()

    // Fixing confirmation submits with username as default display_name when left blank
    fireEvent.change(screen.getByLabelText(/确认密码/), { target: { value: 'password123' } })
    fireEvent.click(screen.getByRole('button', { name: /创建账号并开始/ }))

    await waitFor(() => {
      expect(authMocks.register).toHaveBeenCalledWith({
        username: 'harry',
        password: 'password123',
        display_name: 'harry',
      })
    })
  })

  it('defaults to login when users already exist, preserves typed credentials across tab switch, and supports language switching', async () => {
    vi.spyOn(api, 'authStatus').mockResolvedValue({ has_users: true })
    render(<MemoryRouter><Auth /></MemoryRouter>)

    expect(await screen.findByRole('heading', { level: 2, name: '登录 FitLife Agent' })).toBeInTheDocument()

    // Type credentials in login mode
    fireEvent.change(screen.getByLabelText(/用户名 \/ 邮箱 \/ 手机号/), { target: { value: 'harry@example.com' } })
    fireEvent.change(screen.getByLabelText(/^密码/), { target: { value: 'secret1234' } })

    // Switch to register and back to login -> inputs are preserved!
    fireEvent.click(screen.getByRole('tab', { name: '注册' }))
    expect(screen.getByLabelText(/用户名/)).toHaveValue('harry@example.com')
    expect(screen.getByLabelText(/^密码/)).toHaveValue('secret1234')

    fireEvent.click(screen.getByRole('tab', { name: '登录' }))
    expect(screen.getByLabelText(/用户名 \/ 邮箱 \/ 手机号/)).toHaveValue('harry@example.com')
    expect(screen.getByLabelText(/^密码/)).toHaveValue('secret1234')

    // Switch language directly on the login screen
    fireEvent.click(screen.getByRole('button', { name: 'English' }))
    expect(await screen.findByRole('heading', { level: 2, name: 'Log in to FitLife Agent' })).toBeInTheDocument()
    expect(languageStorage.get()).toBe('en-US')

    fireEvent.click(screen.getByRole('button', { name: 'Login' }))
    await waitFor(() => {
      expect(authMocks.login).toHaveBeenCalledWith({
        identifier: 'harry@example.com',
        password: 'secret1234',
      })
    })
  })
})
