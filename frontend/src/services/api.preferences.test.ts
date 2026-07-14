import { beforeEach, expect, it, vi } from 'vitest'

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

