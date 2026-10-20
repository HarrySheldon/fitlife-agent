import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { coachApi } from '../services/coachApi'
import type { CoachConversation, CoachMessage, CoachSend, CoachTurn } from '../types/coach'
import { holdsCoachSlot } from '../types/coach'

// One controller per authenticated owner; UI visibility never owns execution.
export function useCoachController(owner: string, api = coachApi) {
  const [open, setOpen] = useState(false)
  const [maximized, setMaximized] = useState(false)
  const [conversations, setConversations] = useState<CoachConversation[]>([])
  const [selected, setSelectedState] = useState<string | null>(() => {
    try { return sessionStorage.getItem(`fitlife-coach-selected:${owner}`) } catch { return null }
  })
  const [messages, setMessages] = useState<Record<string, CoachMessage[]>>({})
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [active, setActive] = useState<CoachTurn | null>(null)
  const [lastTurns, setLastTurns] = useState<Record<string, CoachTurn>>({})
  const setLastTurn = (turn: CoachTurn) => setLastTurns(old => ({ ...old, [turn.conversation_id]: turn }))
  const [error, setError] = useState(false)
  const [notice, setNotice] = useState('')
  const [unread, setUnread] = useState(false)
  const [sending, setSending] = useState(false)
  const alive = useRef(true)
  const sendingRef = useRef(false)
  const selectedRef = useRef(selected)
  const openRef = useRef(open)
  const tracked = useRef<CoachTurn | null>(null)
  const requestEpoch = useRef(0)
  const selectionTouched = useRef(false)
  const setSelected = (id: string | null) => {
    // A stop notice belongs to the turn it stopped. Showing it next to a later
    // answer, or in another chat, would read as if that turn had been stopped.
    if (selectedRef.current !== id) setNotice('')
    selectionTouched.current = true
    selectedRef.current = id
    setSelectedState(id)
    try {
      if (id) sessionStorage.setItem(`fitlife-coach-selected:${owner}`, id)
      else sessionStorage.removeItem(`fitlife-coach-selected:${owner}`)
    } catch { /* Only identifiers are optional recovery hints, never chat text. */ }
  }
  selectedRef.current = selected
  openRef.current = open

  useEffect(() => {
    alive.current = true
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      const epoch = requestEpoch.current
      try {
        if (sendingRef.current || epoch !== requestEpoch.current) { timer = setTimeout(poll, 1500); return }
        const result = await api.active()
        if (stopped) return
        if (sendingRef.current || epoch !== requestEpoch.current) { timer = setTimeout(poll, 1500); return }
        setActive(result.turn)
        const previous = tracked.current
        if (previous && previous.turn_id !== result.turn?.turn_id) {
          // The old turn may belong to a deleted chat: never retry its generation.
          try {
            const final = await api.turn(previous.turn_id)
            if (stopped) return
            if (epoch !== requestEpoch.current) { timer = setTimeout(poll, 1500); return }
            setLastTurn(final)
            const updated = await api.messages(final.conversation_id)
            if (stopped) return
            if (epoch !== requestEpoch.current) { timer = setTimeout(poll, 1500); return }
            setMessages(old => ({ ...old, [final.conversation_id]: updated.messages }))
            if (!openRef.current || selectedRef.current !== final.conversation_id) setUnread(true)
          } catch { /* Deleted conversation has no readable transcript. */ }
        }
        if (stopped) return
        if (epoch !== requestEpoch.current) { timer = setTimeout(poll, 1500); return }
        tracked.current = result.turn
      } catch { if (!stopped) setError(true) }
      if (!stopped) timer = setTimeout(poll, 1500)
    }
    void api.list().then(result => {
      if (stopped) return
      setConversations(result.conversations)
      if (!selectionTouched.current) setSelected(
        result.conversations.some(item => item.conversation_id === selectedRef.current)
          ? selectedRef.current : result.conversations[0]?.conversation_id ?? null,
      )
    }).catch(() => { if (!stopped) setError(true) })
    void poll()
    return () => { stopped = true; alive.current = false; clearTimeout(timer) }
  }, [owner, api])

  useEffect(() => {
    if (!selected) return
    let stopped = false
    const epoch = requestEpoch.current
    void api.messages(selected).then(result => {
      if (!stopped && epoch === requestEpoch.current) {
        setMessages(old => ({ ...old, [selected]: result.messages }))
        const latest = result.messages[result.messages.length - 1]
        if (latest) void api.turn(latest.turn_id).then(turn => {
          if (!stopped && epoch === requestEpoch.current) setLastTurn(turn)
        }).catch(() => {})
      }
    }).catch(() => { if (!stopped) setError(true) })
    return () => { stopped = true }
  }, [selected, api])

  const show = () => { setOpen(true); setUnread(false) }
  const newChat = () => { setSelected(null); setError(false); show() }
  const setDraft = (value: string) => setDrafts(old => ({ ...old, [selected ?? 'new']: value }))
  async function send(payload: CoachSend) {
    if (sendingRef.current || holdsCoachSlot(active)) return
    sendingRef.current = true
    requestEpoch.current += 1
    setSending(true)
    setError(false)
    setNotice('')
    show()
    const original = selected
    let targetConversation = original
    try {
      const conversation = original ?? (await api.create(Array.from(payload.question).slice(0, 120).join(''))).conversation_id
      targetConversation = conversation
      if (!alive.current) return
      if (!original) {
        setDrafts(old => ({ ...old, [conversation]: old.new ?? '' }))
        setSelected(conversation)
        const list = await api.list()
        if (!alive.current) return
        setConversations(list.conversations)
      }
      const turn = await api.send(conversation, payload, crypto.randomUUID())
      if (!alive.current) return
      setActive(holdsCoachSlot(turn) ? turn : null)
      tracked.current = turn
      setLastTurn(turn)
      setDrafts(old => {
        const next = { ...old }
        for (const key of new Set([original ?? 'new', conversation])) {
          if (next[key] === payload.question) next[key] = ''
        }
        return next
      })
      const result = await api.messages(conversation)
      if (alive.current) setMessages(old => ({ ...old, [conversation]: result.messages }))
    } catch {
      if (alive.current) {
        setError(true)
        // Unknown POST outcome: only query state, never silently resend.
        try {
          const result = await api.active()
          if (alive.current) { setActive(result.turn); tracked.current = result.turn }
          if (targetConversation) {
            const recovered = await api.messages(targetConversation)
            if (alive.current) setMessages(old => ({ ...old, [targetConversation!]: recovered.messages }))
          }
        } catch { /* retain error */ }
      }
    } finally {
      sendingRef.current = false
      if (alive.current) setSending(false)
    }
  }
  async function stop() {
    if (!active) return
    try {
      const result = await api.cancel(active.turn_id)
      if (alive.current) { setActive(result); setNotice(result.notice) }
    } catch { if (alive.current) setError(true) }
  }
  async function remove(conversation: string) {
    try {
      await api.remove(conversation)
      if (!alive.current) return
      setConversations(old => old.filter(item => item.conversation_id !== conversation))
      setMessages(old => { const next = { ...old }; delete next[conversation]; return next })
      setDrafts(old => { const next = { ...old }; delete next[conversation]; return next })
      setLastTurns(old => { const next = { ...old }; delete next[conversation]; return next })
      if (selectedRef.current === conversation) setSelected(null)
      // Do not clear active: deletion may still be cleaning the transport.
    } catch { if (alive.current) setError(true) }
  }
  async function rename(conversation: string, title: string) {
    try {
      const result = await api.rename(conversation, title)
      if (alive.current) setConversations(old => old.map(item => item.conversation_id === conversation ? result : item))
    } catch { if (alive.current) setError(true) }
  }
  return { open, setOpen, maximized, setMaximized, conversations, selected, setSelected,
    messages: selected ? messages[selected] ?? [] : [], draft: drafts[selected ?? 'new'] ?? '', setDraft,
    active, lastTurn: selected ? lastTurns[selected] ?? null : null, error, notice, unread, sending, show, newChat, send, stop, remove, rename }
}

type Controller = ReturnType<typeof useCoachController>
const CoachContext = createContext<Controller | null>(null)
export function CoachProvider({ owner, children, api = coachApi }: { owner: string; children: ReactNode; api?: typeof coachApi }) {
  return <CoachOwner key={owner} owner={owner} api={api}>{children}</CoachOwner>
}
function CoachOwner({ owner, children, api }: { owner: string; children: ReactNode; api: typeof coachApi }) {
  const controller = useCoachController(owner, api)
  return <CoachContext.Provider value={controller}>{children}</CoachContext.Provider>
}
export const useCoach = () => useContext(CoachContext)
