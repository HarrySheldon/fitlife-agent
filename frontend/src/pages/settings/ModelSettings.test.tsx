import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'

import i18n from '../../i18n'
import { ModelSettings } from './ModelSettings'

const mocks = vi.hoisted(() => ({ workspace: vi.fn(), providers: vi.fn(), probe: vi.fn(), list: vi.fn(), draft: vi.fn(), activate: vi.fn() }))
vi.mock('../../services/api', () => ({ api: {
  modelWorkspace: mocks.workspace, modelProviders: mocks.providers, previewModelTest: mocks.probe,
  previewModels: mocks.list, saveModelDraft: mocks.draft, activateModel: mocks.activate,
} }))

beforeEach(async () => {
  vi.clearAllMocks()
  await i18n.changeLanguage('zh-CN')
  mocks.workspace.mockResolvedValue({ revision: 0, active: null, draft: null })
  mocks.providers.mockResolvedValue({ providers: [{ id: 'custom', display_name: 'Custom', default_base_url: null,
    protocols: ['chat_completions', 'responses'], recommended_protocol: 'chat_completions' }] })
  mocks.probe.mockResolvedValue({ status: 'success', generation: { status: 'passed' }, structured: { status: 'passed' }, verification_token: 'synthetic-token', tested_at: new Date().toISOString() })
})

async function fillForm() {
  render(<MemoryRouter><ModelSettings /></MemoryRouter>)
  await screen.findByLabelText('模型提供商')
  fireEvent.change(screen.getByLabelText('模型提供商'), { target: { value: 'custom' } })
  fireEvent.change(screen.getByLabelText('基础 URL'), { target: { value: 'https://models.example.com/v1' } })
  fireEvent.change(screen.getByLabelText('API 密钥'), { target: { value: 'synthetic-key' } })
  fireEvent.change(screen.getByLabelText('模型名称'), { target: { value: 'candidate' } })
}

it('tests the current form, then invalidates verification after a model change', async () => {
  await fillForm()
  const enable = screen.getByRole('button', { name: '保存并启用' })
  expect(enable).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '测试连接' }))
  await waitFor(() => expect(enable).toBeEnabled())
  expect(screen.getByText('连接测试通过，可以保存并启用。实际业务结果仍会逐次校验。')).toBeVisible()
  expect(screen.queryByText('工具调用')).not.toBeInTheDocument()
  const details = screen.getByText('测试详情').closest('details')!
  expect(details.open).toBe(false)
  fireEvent.click(screen.getByText('测试详情'))
  expect(screen.getByText('业务数据解析')).toBeVisible()
  expect(mocks.probe).toHaveBeenCalledWith(expect.objectContaining({ base_url: 'https://models.example.com/v1', model: 'candidate', api_key: 'synthetic-key' }), expect.any(AbortSignal))
  expect(mocks.activate).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('模型名称'), { target: { value: 'another' } })
  expect(enable).toBeDisabled()
})

it('keeps manual model entry available when model discovery fails', async () => {
  mocks.list.mockRejectedValue(new Error('Discovery unsupported'))
  await fillForm()
  fireEvent.click(screen.getByRole('button', { name: '获取模型' }))
  await screen.findByText('Discovery unsupported')
  expect(screen.getByLabelText('模型名称')).toBeEnabled()
  expect(screen.getByRole('button', { name: '测试连接' })).toBeEnabled()
  expect(mocks.probe).not.toHaveBeenCalled()
})

it('does not enable a connection when only generation passes', async () => {
  mocks.probe.mockResolvedValue({ status: 'failed', generation: { status: 'passed' }, structured: { status: 'failed' }, verification_token: null, tested_at: new Date().toISOString() })
  await fillForm()
  fireEvent.click(screen.getByRole('button', { name: '测试连接' }))
  await screen.findByText(/当前配置无法完成本项目所需的数据解析/)
  expect(screen.getByRole('button', { name: '保存并启用' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '保存为停用草稿' })).toBeEnabled()
})

it('does not perform a model request on load, enter, or save draft', async () => {
  mocks.draft.mockResolvedValue({ revision: 1, active: null, draft: { provider: 'custom', protocol: 'chat_completions',
    base_url: 'https://models.example.com/v1', model: 'candidate', enabled: false, api_key_configured: true } })
  await fillForm()
  fireEvent.submit(screen.getByLabelText('模型名称').closest('form')!)
  expect(mocks.probe).not.toHaveBeenCalled()
  expect(mocks.list).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '保存为停用草稿' }))
  await screen.findByText(/已保存为停用草稿/)
  expect(mocks.probe).not.toHaveBeenCalled()
  expect(mocks.activate).not.toHaveBeenCalled()
})


it('shows a connection failure separately from business parsing and keeps details collapsed', async () => {
  mocks.probe.mockResolvedValue({ status: 'failed', generation: { status: 'failed', error_code: 'MODEL_AUTH_FAILED' },
    structured: { status: 'not_run' }, verification_token: null, tested_at: new Date().toISOString() })
  await fillForm()
  fireEvent.click(screen.getByRole('button', { name: '测试连接' }))
  await screen.findByText(/连接测试失败，请检查地址/)
  expect(screen.getByRole('button', { name: '保存并启用' })).toBeDisabled()
  expect(screen.getByText('测试详情').closest('details')!.open).toBe(false)
})
