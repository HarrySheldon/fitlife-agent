// Dev-only, entirely in-memory UI fixture. No backend, credentials or real records.
import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { CoachProvider, useCoach } from '../src/hooks/useCoach'
import { CoachWindow } from '../src/components/coach/CoachWindow'
import i18n from '../src/i18n'
import '../src/styles/index.css'
import type { coachApi } from '../src/services/coachApi'
import type { CoachConversation, CoachMessage, CoachTurn } from '../src/types/coach'

if (!import.meta.env.DEV) throw new Error('Synthetic fixture is development-only')
void i18n.changeLanguage('zh-CN')
const conversations: CoachConversation[] = []
const messages: Record<string, CoachMessage[]> = {}
const turns: Record<string, CoachTurn> = {}
let active: CoachTurn | null = null
let calls = 0
const now = () => new Date().toISOString()
const api: typeof coachApi = {
  list: async () => ({ conversations: [...conversations] }),
  create: async title => {
    const record = { conversation_id: `fixture-${crypto.randomUUID()}`, title: title ?? null, created_at: now(), updated_at: now() }
    conversations.push(record)
    messages[record.conversation_id] = []
    return record
  },
  messages: async id => ({ messages: [...messages[id] ?? []] }),
  active: async () => ({ turn: active }),
  turn: async id => ({ ...turns[id] }),
  send: async (id, payload, key) => {
    if (active) throw new Error('Busy')
    calls++
    const turn: CoachTurn = { turn_id: key, conversation_id: id, status: 'running', stopping: false, receipt: null, error_code: null }
    turns[key] = turn
    active = turn
    messages[id].push({ message_id: `${key}-user`, turn_id: key, role: 'user', body: payload.question, created_at: now() })
    setTimeout(() => {
      if (turn.status !== 'running') return
      turn.status = 'succeeded'
      active = null
      messages[id].push({ message_id: `${key}-coach`, turn_id: key, role: 'coach',
        body: '今天可以从稳定饮食和适度训练开始。\n\n- 留意蛋白质来源的多样性。\n- 根据疲劳程度调整训练。\n\n如有不适，请先休息。', created_at: now(),
        metadata: { model: 'synthetic-no-provider', sources: [{ source: 'synthetic-nutrition', heading: '合成营养知识' }], context: { action: payload.action, date: payload.date } } })
    }, 8000)
    return { ...turn }
  },
  cancel: async id => {
    const turn = turns[id]
    turn.stopping = true
    setTimeout(() => { turn.status = 'cancelled'; turn.stopping = false; active = null }, 800)
    return { ...turn, notice: '合成请求，无真实费用。' }
  },
  remove: async id => {
    const index = conversations.findIndex(item => item.conversation_id === id)
    if (index >= 0) conversations.splice(index, 1)
    delete messages[id]
    if (active?.conversation_id === id) { active.status = 'cancelled'; active = null }
    return { deleted: true }
  },
  rename: async (id, title) => {
    const record = conversations.find(item => item.conversation_id === id)!
    record.title = title
    return { ...record }
  },
}
function Surface() {
  const coach = useCoach()!
  const [draft, setDraft] = useState('业务表单草稿，请勿重置')
  const [counter, setCounter] = useState(0)
  return <main style={{ padding: 24 }}>
    <h1>C3 合成界面验收</h1><p>仅内存假数据，不访问真实账户或模型。</p>
    <label>业务草稿<input value={draft} onChange={event => setDraft(event.target.value)} /></label>
    <button onClick={() => { setCounter(counter + 1) }}>背景操作 {counter}</button>
    <button onClick={() => void coach.send({ action: 'explain_today', surface: 'today', date: '2026-10-19', question: '解释今天 · 2026-10-19' })}>解释今天</button>
    <p>合成模型请求：{calls}</p>
    <CoachWindow />
  </main>
}
function Harness() {
  const [width, setWidth] = useState(375)
  if (new URLSearchParams(location.search).has('frame')) return <CoachProvider owner="synthetic-browser" api={api}><Surface /></CoachProvider>
  return <><label>验收宽度<select value={width} onChange={event => setWidth(Number(event.target.value))}>{[375, 768, 1024, 1440].map(value => <option key={value}>{value}</option>)}</select></label>
    <iframe title="合成应用" src="/e2e/coach.html?frame=1" style={{ display: 'block', width, height: 900, border: '1px solid #777' }} />
  </>
}
createRoot(document.getElementById('root')!).render(<Harness />)
