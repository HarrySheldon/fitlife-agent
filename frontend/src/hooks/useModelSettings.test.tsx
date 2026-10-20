import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

import { useModelSettings } from './useModelSettings'

const mocks = vi.hoisted(() => ({ workspace: vi.fn(), providers: vi.fn(), probe: vi.fn(), models: vi.fn() }))
vi.mock('../services/api', () => ({ api: {
  modelWorkspace: mocks.workspace, modelProviders: mocks.providers, previewModelTest: mocks.probe, previewModels: mocks.models,
} }))

beforeEach(() => {
  mocks.workspace.mockResolvedValue({ revision: 0, active: null, draft: null })
  mocks.providers.mockResolvedValue({ providers: [] })
  mocks.probe.mockReset()
  mocks.models.mockReset()
})

it('ignores a successful probe if the form changed while it was running', async () => {
  let resolve: (value: unknown) => void = () => {}
  mocks.probe.mockReturnValue(new Promise(done => { resolve = done }))
  const { result } = renderHook(() => useModelSettings())
  await waitFor(() => expect(result.current.loading).toBe(false))
  act(() => result.current.patch({ provider_id: 'custom', base_url: 'https://models.example.com/v1', model: 'a', api_key: 'synthetic' }))
  let request: Promise<unknown>
  act(() => { request = result.current.testConnection() })
  act(() => result.current.patch({ model: 'b' }))
  await act(async () => {
    resolve({ status: 'success', generation: { status: 'passed' }, structured: { status: 'passed' }, verification_token: 'old-token' })
    await request
  })
  expect(result.current.verificationToken).toBeNull()
  expect(result.current.editing.model).toBe('b')
})


it('preserves local edits on revision refresh and invalidates verification', async () => {
  mocks.probe.mockResolvedValue({ status: 'success', generation: { status: 'passed' }, structured: { status: 'passed' }, verification_token: 'token', tested_at: new Date().toISOString() })
  const { result } = renderHook(() => useModelSettings())
  await waitFor(() => expect(result.current.loading).toBe(false))
  act(() => result.current.patch({ provider_id: 'custom', base_url: 'https://models.example.com/v1', model: 'local-edit', api_key: 'synthetic' }))
  await act(async () => { await result.current.testConnection() })
  expect(result.current.verificationToken).toBe('token')
  mocks.workspace.mockResolvedValue({ revision: 3, active: null, draft: null })
  await act(async () => { await result.current.refresh() })
  expect(result.current.editing.model).toBe('local-edit')
  expect(result.current.editing.api_key).toBe('synthetic')
  expect(result.current.editing.expected_revision).toBe(3)
  expect(result.current.verificationToken).toBeNull()
})


it('does not send a saved credential to a changed address when confirmation is declined', async () => {
  mocks.workspace.mockResolvedValue({ revision: 1, active: { provider: 'custom', provider_id: 'custom', base_url: 'https://old.example.com/v1',
    protocol: 'chat_completions', model: 'old', api_key_configured: true }, draft: null })
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  try {
    const { result } = renderHook(() => useModelSettings())
    await waitFor(() => expect(result.current.loading).toBe(false))
    act(() => result.current.patch({ base_url: 'https://new.example.com/v1' }))
    expect(result.current.editing.credential_mode).toBe('new')
    act(() => result.current.patch({ credential_mode: 'reuse_active' }))
    await act(async () => { await result.current.testConnection() })
    expect(confirm).toHaveBeenCalled()
    expect(mocks.probe).not.toHaveBeenCalled()
  } finally {
    confirm.mockRestore()
  }
})


it('aborts the preview fetch when the page unmounts', async () => {
  mocks.probe.mockReturnValue(new Promise(() => {}))
  const { result, unmount } = renderHook(() => useModelSettings())
  await waitFor(() => expect(result.current.loading).toBe(false))
  act(() => result.current.patch({ provider_id: 'custom', base_url: 'https://models.example.com/v1', model: 'a', api_key: 'synthetic' }))
  act(() => { void result.current.testConnection() })
  const signal = mocks.probe.mock.calls[0][1] as AbortSignal
  expect(signal.aborted).toBe(false)
  unmount()
  expect(signal.aborted).toBe(true)
})


it('does not accept an aggregate success or token when business parsing failed', async () => {
  mocks.probe.mockResolvedValue({ status: 'success', generation: { status: 'passed' },
    structured: { status: 'failed' }, verification_token: 'invalid-success' })
  const { result } = renderHook(() => useModelSettings())
  await waitFor(() => expect(result.current.loading).toBe(false))
  act(() => result.current.patch({ provider_id: 'custom', base_url: 'https://models.example.com/v1', model: 'a', api_key: 'synthetic' }))
  await act(async () => { await result.current.testConnection() })
  expect(result.current.verificationToken).toBeNull()
})
