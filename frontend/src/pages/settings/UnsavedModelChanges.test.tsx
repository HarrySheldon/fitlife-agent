import { act, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { expect, it, vi } from 'vitest'

import { UnsavedModelChanges } from './UnsavedModelChanges'

it('blocks browser-style history navigation until the user confirms', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  const router = createMemoryRouter([
    { path: '/settings', element: <h1>Settings destination</h1> },
    { path: '/model', element: <><UnsavedModelChanges dirty /><h1>Editing connection</h1></> },
  ], { initialEntries: ['/settings', '/model'], initialIndex: 1 })
  try {
    render(<RouterProvider router={router} />)
    await act(async () => { await router.navigate(-1) })
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1))
    expect(router.state.location.pathname).toBe('/model')
    expect(screen.getByText('Editing connection')).toBeInTheDocument()
    confirm.mockReturnValue(true)
    await act(async () => { await router.navigate(-1) })
    await screen.findByText('Settings destination')
  } finally {
    confirm.mockRestore()
    router.dispose()
  }
})
