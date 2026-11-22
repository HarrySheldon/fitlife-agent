import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'

import i18n from '../../i18n'
import { UnsavedModelChanges } from './UnsavedModelChanges'

beforeEach(async () => {
  await i18n.changeLanguage('en-US')
})

it('blocks browser-style history navigation with a custom confirmation modal until the user confirms', async () => {
  const nativeConfirm = vi.spyOn(window, 'confirm')
  const router = createMemoryRouter([
    { path: '/settings', element: <h1>Settings destination</h1> },
    { path: '/model', element: <><UnsavedModelChanges dirty /><h1>Editing connection</h1></> },
  ], { initialEntries: ['/settings', '/model'], initialIndex: 1 })
  try {
    render(<RouterProvider router={router} />)
    await act(async () => { await router.navigate(-1) })
    expect(await screen.findByRole('dialog', { name: 'Discard unsaved changes?' })).toBeInTheDocument()
    expect(nativeConfirm).not.toHaveBeenCalled()
    expect(router.state.location.pathname).toBe('/model')

    // Choosing "Keep editing" stays on the page
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(router.state.location.pathname).toBe('/model')
    expect(screen.getByText('Editing connection')).toBeInTheDocument()

    // Trying again and confirming proceeds
    await act(async () => { await router.navigate(-1) })
    expect(await screen.findByRole('dialog', { name: 'Discard unsaved changes?' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Discard & continue' }))
    await screen.findByText('Settings destination')
  } finally {
    nativeConfirm.mockRestore()
    router.dispose()
  }
})
