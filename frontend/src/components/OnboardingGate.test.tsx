import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ProfileSetup } from '../types'
import { OnboardingGate } from './OnboardingGate'


const gate = vi.hoisted(() => ({
  setup: null as ProfileSetup | null,
  loading: false,
  error: null as string | null,
  refresh: vi.fn(),
}))

vi.mock('../hooks/useProfileSetup', () => ({
  useProfileSetup: () => ({
    setup: gate.setup,
    loading: gate.loading,
    error: gate.error,
    refresh: gate.refresh,
  }),
}))

function renderGate() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route element={<OnboardingGate />}>
          <Route path="/" element={<h1>Application shell</h1>} />
        </Route>
        <Route path="/onboarding" element={<h1>Onboarding destination</h1>} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  gate.setup = null
  gate.loading = false
  gate.error = null
  gate.refresh.mockReset()
})

describe('OnboardingGate', () => {
  it('waits for setup status before rendering the application shell', () => {
    gate.loading = true
    renderGate()

    expect(screen.getByText('Loading profile setup...')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Application shell' })).not.toBeInTheDocument()
  })

  it('redirects incomplete users to onboarding', async () => {
    gate.setup = { profile: null, goal: null, target: null, setup_complete: false }
    renderGate()

    expect(await screen.findByRole('heading', { name: 'Onboarding destination' })).toBeInTheDocument()
  })

  it('renders the application shell only for complete users', () => {
    gate.setup = {
      profile: {} as ProfileSetup['profile'],
      goal: {} as ProfileSetup['goal'],
      target: {} as ProfileSetup['target'],
      setup_complete: true,
    }
    renderGate()

    expect(screen.getByRole('heading', { name: 'Application shell' })).toBeInTheDocument()
  })

  it('shows a retryable error instead of bypassing the gate', () => {
    gate.error = 'Setup status unavailable'
    renderGate()

    expect(screen.getByText('Setup status unavailable')).toBeInTheDocument()
    screen.getByRole('button', { name: 'Try again' }).click()
    expect(gate.refresh).toHaveBeenCalledOnce()
  })
})
