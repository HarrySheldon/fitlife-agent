import { beforeEach, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import { api } from './api'


beforeEach(() => {
  window.localStorage.clear()
  vi.restoreAllMocks()
})

it('sends cached language and browser timezone on preference initialization', async () => {
  window.localStorage.setItem('fitlife_language', 'zh-CN')
  vi.spyOn(Intl, 'DateTimeFormat').mockReturnValue({
    resolvedOptions: () => ({ timeZone: 'Asia/Shanghai' }),
  } as Intl.DateTimeFormat)
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    success: true,
    data: { language: 'zh-CN', unit_system: 'metric', timezone: 'Asia/Shanghai' },
    message: '',
  }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

  await api.preferences()

  const headers = new Headers(fetchMock.mock.calls[0][1]?.headers)
  expect(headers.get('Accept-Language')).toBe('zh-CN')
  expect(headers.get('X-Timezone')).toBe('Asia/Shanghai')
})

it.each([
  ['en-US' as const, 'Request failed (503).'],
  ['zh-CN' as const, '请求失败（503）。'],
])('localizes an empty API failure in %s', async (language, expected) => {
  window.localStorage.setItem('fitlife_language', language)
  await i18n.changeLanguage(language)
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 503 }))

  await expect(api.preferences()).rejects.toMatchObject({ message: expected, status: 503 })
})
