import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'

import { GeneralSettings } from './GeneralSettings'


const mocks = vi.hoisted(() => ({
  update: vi.fn(),
}))

vi.mock('../../hooks/usePreferences', () => ({
  usePreferences: () => ({
    preferences: { language: 'en-US', unit_system: 'metric', timezone: 'UTC' },
    loading: false,
    error: null,
    updatePreferences: mocks.update,
  }),
}))

beforeEach(() => mocks.update.mockReset().mockResolvedValue(undefined))

it('updates language, descriptive units, and timezone independently', async () => {
  render(<MemoryRouter><GeneralSettings /></MemoryRouter>)

  fireEvent.click(screen.getByRole('radio', { name: /Imperial/ }))
  fireEvent.click(screen.getByRole('button', { name: '中文' }))
  fireEvent.change(screen.getByLabelText('Time zone'), { target: { value: 'Asia/Shanghai' } })

  await waitFor(() => expect(mocks.update).toHaveBeenCalledWith({ unit_system: 'imperial' }))
  expect(mocks.update).toHaveBeenCalledWith({ language: 'zh-CN' })
  expect(mocks.update).toHaveBeenCalledWith({ timezone: 'Asia/Shanghai' })
})

