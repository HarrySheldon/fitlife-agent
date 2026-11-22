import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../../i18n'
import { ModelSettings } from './ModelSettings'

const mocks = vi.hoisted(() => ({
  workspace: vi.fn(),
  providers: vi.fn(),
  probe: vi.fn(),
  list: vi.fn(),
  draft: vi.fn(),
  activate: vi.fn(),
  disable: vi.fn(),
  clear: vi.fn(),
}))

vi.mock('../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      modelWorkspace: mocks.workspace,
      modelProviders: mocks.providers,
      previewModelTest: mocks.probe,
      previewModels: mocks.list,
      saveModelDraft: mocks.draft,
      activateModel: mocks.activate,
      disableModel: mocks.disable,
      clearModelCredential: mocks.clear,
    },
  }
})

const defaultProviders = [
  {
    id: 'deepseek',
    display_name: 'DeepSeek',
    default_base_url: 'https://api.deepseek.com/v1',
    protocols: ['chat_completions'],
    recommended_protocol: 'chat_completions',
    recommended_models: ['deepseek-chat', 'deepseek-reasoner'],
  },
  {
    id: 'custom',
    display_name: 'Custom compatible service',
    default_base_url: null,
    protocols: ['chat_completions', 'responses'],
    recommended_protocol: 'chat_completions',
    recommended_models: [],
  },
]

beforeEach(async () => {
  vi.clearAllMocks()
  await i18n.changeLanguage('zh-CN')
  mocks.workspace.mockResolvedValue({ revision: 0, active: null, draft: null })
  mocks.providers.mockResolvedValue({ providers: defaultProviders })
  mocks.probe.mockResolvedValue({
    status: 'success',
    generation: { status: 'passed', latency_ms: 320 },
    structured: { status: 'passed', latency_ms: 480 },
    verification_token: 'synthetic-token',
    tested_at: new Date().toISOString(),
  })
})

async function renderCustomFilled(route = '/settings/model') {
  render(<MemoryRouter initialEntries={[route]}><ModelSettings /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('radio', { name: /自定义兼容服务/ }))
  fireEvent.change(screen.getByLabelText('基础 URL'), { target: { value: 'https://models.example.com/v1' } })
  fireEvent.change(screen.getByLabelText('API 密钥'), { target: { value: 'synthetic-key' } })
  fireEvent.change(screen.getByLabelText('模型名称'), { target: { value: 'candidate' } })
}

describe('ModelSettings UX-1', () => {
  it('supports provider preset selection, recommended model chips, key visibility toggle, and one-click test & enable', async () => {
    mocks.activate.mockResolvedValue({
      revision: 1,
      active: {
        provider: 'custom',
        provider_id: 'deepseek',
        protocol: 'chat_completions',
        base_url: 'https://api.deepseek.com/v1',
        model: 'deepseek-chat',
        enabled: true,
        api_key_configured: true,
        api_key_hint: 'sk-***1234',
        generation_status: 'passed',
        structured_status: 'passed',
      },
      draft: null,
    })

    render(<MemoryRouter initialEntries={['/settings/model?returnTo=/coach']}><ModelSettings /></MemoryRouter>)

    // Auto-selects first preset (DeepSeek) with recommended model chips ready
    const keyInput = await screen.findByLabelText('API 密钥')
    expect(keyInput).toHaveAttribute('type', 'password')
    fireEvent.click(screen.getByRole('button', { name: '显示密钥' }))
    expect(keyInput).toHaveAttribute('type', 'text')

    fireEvent.change(keyInput, { target: { value: '  sk-test-1234  ' } })
    fireEvent.blur(keyInput)
    expect(keyInput).toHaveValue('sk-test-1234')

    fireEvent.click(screen.getByRole('button', { name: 'deepseek-chat' }))
    expect(screen.getByLabelText('模型名称')).toHaveValue('deepseek-chat')

    // One-click Test and Enable tests then activates automatically
    fireEvent.click(screen.getByRole('button', { name: '测试并启用' }))

    await waitFor(() => expect(mocks.activate).toHaveBeenCalledTimes(1))
    expect(mocks.probe).toHaveBeenCalledWith(
      expect.objectContaining({
        provider_id: 'deepseek',
        base_url: 'https://api.deepseek.com/v1',
        model: 'deepseek-chat',
        api_key: 'sk-test-1234',
      }),
      expect.any(AbortSignal),
    )
    expect(mocks.activate).toHaveBeenCalledWith(
      expect.objectContaining({
        provider_id: 'deepseek',
        model: 'deepseek-chat',
        verification_token: 'synthetic-token',
      }),
    )

    // Post-activation CTA routes back to caller (/coach)
    const backLink = await screen.findByRole('link', { name: /返回教练工作台/ })
    expect(backLink).toHaveAttribute('href', '/coach')
  })

  it('opens searchable model combobox after fetching models and allows manual entry on failure', async () => {
    mocks.list.mockResolvedValueOnce({ models: ['gpt-4.1-mini', 'deepseek-chat'], truncated: false })
    await renderCustomFilled()

    fireEvent.click(screen.getByRole('button', { name: '获取模型' }))
    const listbox = await screen.findByRole('listbox')
    expect(listbox).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'gpt-4.1-mini' }))
    expect(screen.getByLabelText('模型名称')).toHaveValue('gpt-4.1-mini')

    mocks.list.mockRejectedValueOnce(new Error('Discovery unsupported'))
    fireEvent.click(screen.getByRole('button', { name: '获取模型' }))
    await screen.findByText('Discovery unsupported')
    expect(screen.getByLabelText('模型名称')).toBeEnabled()
    expect(mocks.probe).not.toHaveBeenCalled()
  })

  it('warns immediately on local HTTP / Ollama URLs and disables test buttons', async () => {
    render(<MemoryRouter><ModelSettings /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('radio', { name: /自定义兼容服务/ }))
    fireEvent.change(screen.getByLabelText('基础 URL'), { target: { value: 'http://localhost:11434/v1' } })
    fireEvent.change(screen.getByLabelText('API 密钥'), { target: { value: 'synthetic-key' } })
    fireEvent.change(screen.getByLabelText('模型名称'), { target: { value: 'llama3' } })

    expect(screen.getByRole('alert')).toHaveTextContent(/公网 HTTPS 地址/)
    expect(screen.getByRole('button', { name: '测试并启用' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '仅测试' })).toBeDisabled()
  })

  it('does not enable when only generation passes and shows human-readable structured parsing diagnosis', async () => {
    mocks.probe.mockResolvedValue({
      status: 'failed',
      generation: { status: 'passed', latency_ms: 210 },
      structured: { status: 'failed', latency_ms: 410 },
      verification_token: null,
      tested_at: new Date().toISOString(),
    })
    await renderCustomFilled()
    fireEvent.click(screen.getByRole('button', { name: '测试并启用' }))

    await screen.findByText(/基础对话连通，但模型未能按 JSON 结构输出业务数据/)
    expect(mocks.activate).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '暂存为草稿' })).toBeEnabled()
    const details = screen.getByText('测试详情').closest('details')!
    expect(details.open).toBe(false)
  })

  it('maps auth failure error codes to actionable guidance and keeps details collapsed', async () => {
    mocks.probe.mockResolvedValue({
      status: 'failed',
      generation: { status: 'failed', error_code: 'MODEL_AUTH_FAILED', latency_ms: 150 },
      structured: { status: 'not_run' },
      verification_token: null,
      tested_at: new Date().toISOString(),
    })
    await renderCustomFilled()
    fireEvent.click(screen.getByRole('button', { name: '仅测试' }))

    await screen.findByText(/API 密钥无效或已过期/)
    expect(mocks.activate).not.toHaveBeenCalled()
    expect(screen.getByText('测试详情').closest('details')!.open).toBe(false)
  })

  it('does not perform a model request on load, enter, or save draft', async () => {
    mocks.draft.mockResolvedValue({
      revision: 1,
      active: null,
      draft: {
        provider: 'custom',
        provider_id: 'custom',
        protocol: 'chat_completions',
        base_url: 'https://models.example.com/v1',
        model: 'candidate',
        enabled: false,
        api_key_configured: true,
      },
    })
    await renderCustomFilled()
    fireEvent.submit(screen.getByLabelText('模型名称').closest('form')!)
    expect(mocks.probe).not.toHaveBeenCalled()
    expect(mocks.list).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '暂存为草稿' }))
    await screen.findByText(/已保存为停用草稿/)
    expect(mocks.probe).not.toHaveBeenCalled()
    expect(mocks.activate).not.toHaveBeenCalled()
  })

  it('uses custom modal instead of window.confirm when disabling an active connection', async () => {
    const nativeConfirm = vi.spyOn(window, 'confirm')
    mocks.workspace.mockResolvedValue({
      revision: 2,
      active: {
        provider: 'custom',
        provider_id: 'deepseek',
        protocol: 'chat_completions',
        base_url: 'https://api.deepseek.com/v1',
        model: 'deepseek-chat',
        enabled: true,
        api_key_configured: true,
        api_key_hint: 'sk-***1234',
        generation_status: 'passed',
        structured_status: 'passed',
      },
      draft: null,
    })
    mocks.disable.mockResolvedValue({
      revision: 3,
      active: {
        provider: 'custom',
        provider_id: 'deepseek',
        protocol: 'chat_completions',
        base_url: 'https://api.deepseek.com/v1',
        model: 'deepseek-chat',
        enabled: false,
        api_key_configured: true,
        api_key_hint: 'sk-***1234',
      },
      draft: null,
    })

    try {
      render(<MemoryRouter><ModelSettings /></MemoryRouter>)
      fireEvent.click(await screen.findByRole('button', { name: '停用当前连接' }))
      expect(nativeConfirm).not.toHaveBeenCalled()
      expect(screen.getByRole('dialog', { name: '停用当前模型连接？' })).toBeInTheDocument()
      const dialogButtons = screen.getAllByRole('button', { name: '停用当前连接' })
      fireEvent.click(dialogButtons[dialogButtons.length - 1])
      await waitFor(() => expect(mocks.disable).toHaveBeenCalledWith(2))
    } finally {
      nativeConfirm.mockRestore()
    }
  })
})
