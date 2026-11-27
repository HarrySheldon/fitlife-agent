import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { coachApi } from '../services/coachApi'
import type {
  CoachConversation,
  CoachMessage,
  CoachSend,
  CoachStreamEvent,
  CoachStreamProgressEvent,
  CoachTurn,
} from '../types/coach'
import { holdsCoachSlot } from '../types/coach'

export type CoachReadDomain = 'profile' | 'training' | 'diet'
export type CoachApiClient = Omit<typeof coachApi, 'streamTurn'> & {
  streamTurn?: typeof coachApi.streamTurn
}
const DEFAULT_READ_DOMAINS: CoachReadDomain[] = ['profile', 'training', 'diet']

// One controller per authenticated owner; UI visibility never owns execution.
export function useCoachController(owner: string, api: CoachApiClient = coachApi) {
  const [open, setOpen] = useState(false)
  const [maximized, setMaximized] = useState(false)
  const [conversations, setConversations] = useState<CoachConversation[]>([])
  const [selected, setSelectedState] = useState<string | null>(() => {
    try { return sessionStorage.getItem(`fitlife-coach-selected:${owner}`) } catch { return null }
  })
  const [messages, setMessages] = useState<Record<string, CoachMessage[]>>({})
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [readDomains, setReadDomains] = useState<CoachReadDomain[]>(DEFAULT_READ_DOMAINS)
  const [active, setActive] = useState<CoachTurn | null>(null)
  const [lastTurns, setLastTurns] = useState<Record<string, CoachTurn>>({})
  const setLastTurn = (turn: CoachTurn) => setLastTurns(old => ({ ...old, [turn.conversation_id]: turn }))
  const [error, setError] = useState(false)
  const [notice, setNotice] = useState('')
  const [unread, setUnread] = useState(false)
  const [sending, setSending] = useState(false)
  const [supportsReadConsent, setSupportsReadConsent] = useState(false)
  const [capabilitiesReady, setCapabilitiesReady] = useState(false)
  const [streamSteps, setStreamSteps] = useState<CoachStreamProgressEvent[]>([])
  const [streamingBody, setStreamingBody] = useState('')
  const [streamingConversationId, setStreamingConversationId] = useState<string | null>(null)
  const alive = useRef(true)
  const sendingRef = useRef(false)
  const selectedRef = useRef(selected)
  const openRef = useRef(open)
  const tracked = useRef<CoachTurn | null>(null)
  const streamAbortRef = useRef<AbortController | null>(null)
  const streamingTurnIdRef = useRef<string | null>(null)
  const requestEpoch = useRef(0)
  const selectionTouched = useRef(false)

  const clearStreamState = () => {
    streamAbortRef.current?.abort()
    streamAbortRef.current = null
    streamingTurnIdRef.current = null
    setStreamSteps([])
    setStreamingBody('')
    setStreamingConversationId(null)
  }

  const startTurnStream = (turn: CoachTurn) => {
    const streamFn = (api as Partial<typeof coachApi>).streamTurn
    if (typeof streamFn !== 'function' || !holdsCoachSlot(turn)) return
    if (streamingTurnIdRef.current === turn.turn_id) return
    streamAbortRef.current?.abort()
    const controller = new AbortController()
    streamAbortRef.current = controller
    streamingTurnIdRef.current = turn.turn_id
    setStreamingConversationId(turn.conversation_id)
    setStreamSteps([])
    setStreamingBody('')
    void streamFn(turn.turn_id, {
      signal: controller.signal,
      onEvent: (ev: CoachStreamEvent) => {
        if (!alive.current || controller.signal.aborted || streamingTurnIdRef.current !== turn.turn_id) return
        if (ev.event === 'step_progress') {
          setStreamSteps(old => {
            const last = old[old.length - 1]
            if (last && last.stage === ev.data.stage && last.status === ev.data.status) return old
            return [...old.slice(-11), ev.data]
          })
          return
        }
        if (ev.event === 'answer_delta') {
          setStreamingBody(old => old + ev.data.delta)
          return
        }
        if (ev.event === 'turn_done') {
          streamingTurnIdRef.current = null
          streamAbortRef.current = null
          setStreamSteps([])
          setStreamingBody('')
          setStreamingConversationId(null)
          setActive(null)
          tracked.current = null
          setLastTurn(ev.data.turn)
          const msg = ev.data.message
          if (msg) {
            setMessages(old => {
              const existing = old[ev.data.turn.conversation_id] ?? []
              if (existing.some(item => item.message_id === msg.message_id)) return old
              return { ...old, [ev.data.turn.conversation_id]: [...existing, msg] }
            })
          }
          void api.messages(ev.data.turn.conversation_id).then(updated => {
            if (alive.current) setMessages(old => ({ ...old, [ev.data.turn.conversation_id]: updated.messages }))
          }).catch(() => {})
          if (!openRef.current || selectedRef.current !== ev.data.turn.conversation_id) setUnread(true)
          return
        }
        if (ev.event === 'turn_error') {
          streamingTurnIdRef.current = null
          streamAbortRef.current = null
          setStreamSteps([])
          setStreamingBody('')
          setStreamingConversationId(null)
          setActive(null)
          tracked.current = null
          void api.turn(ev.data.turn_id).then(final => {
            if (alive.current) setLastTurn(final)
          }).catch(() => {})
        }
      },
      onClose: () => {
        if (streamingTurnIdRef.current === turn.turn_id) {
          streamingTurnIdRef.current = null
        }
      },
      onError: () => {
        if (streamingTurnIdRef.current === turn.turn_id) {
          streamingTurnIdRef.current = null
        }
      },
    })
  }
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

  const toggleReadDomain = (domain: CoachReadDomain) => {
    setReadDomains(current =>
      current.includes(domain)
        ? current.filter(item => item !== domain)
        : [...current, domain],
    )
  }

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
        setSupportsReadConsent(result.capabilities?.explicit_read_scope === true)
        setCapabilitiesReady(true)
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
        if (result.turn && holdsCoachSlot(result.turn)) {
          startTurnStream(result.turn)
        }
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
    return () => { stopped = true; alive.current = false; clearTimeout(timer); clearStreamState() }
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
  const clearUnread = () => { setUnread(false) }
  const newChat = (options?: { openWindow?: boolean }) => {
    setSelected(null)
    setError(false)
    if (options?.openWindow !== false) show()
    else clearUnread()
  }
  const setDraft = (value: string) => setDrafts(old => ({ ...old, [selected ?? 'new']: value }))
  async function send(payload: CoachSend, options?: { openWindow?: boolean }): Promise<boolean> {
    if (sendingRef.current || holdsCoachSlot(active)) return false
    sendingRef.current = true
    requestEpoch.current += 1
    setSending(true)
    setError(false)
    setNotice('')
    if (options?.openWindow !== false) show()
    else clearUnread()
    const original = selected
    let targetConversation = original
    try {
      const conversation = original ?? (await api.create(Array.from(payload.question).slice(0, 120).join(''))).conversation_id
      targetConversation = conversation
      if (!alive.current) return false
      if (!original) {
        setDrafts(old => ({ ...old, [conversation]: old.new ?? '' }))
        setSelected(conversation)
        const list = await api.list()
        if (!alive.current) return false
        setConversations(list.conversations)
      }
      const turn = await api.send(conversation, payload, crypto.randomUUID())
      if (!alive.current) return false
      setActive(holdsCoachSlot(turn) ? turn : null)
      tracked.current = turn
      setLastTurn(turn)
      if (holdsCoachSlot(turn)) {
        startTurnStream(turn)
      }
      setDrafts(old => {
        const next = { ...old }
        for (const key of new Set([original ?? 'new', conversation])) {
          if (next[key] === payload.question) next[key] = ''
        }
        return next
      })
      const result = await api.messages(conversation)
      if (alive.current) setMessages(old => ({ ...old, [conversation]: result.messages }))
      return true
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
      return false
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
  return {
    open, setOpen, maximized, setMaximized, conversations, selected, setSelected,
    messages: selected ? messages[selected] ?? [] : [],
    draft: drafts[selected ?? 'new'] ?? '', setDraft,
    readDomains, setReadDomains, toggleReadDomain,
    active, lastTurn: selected ? lastTurns[selected] ?? null : null,
    error, notice, unread, clearUnread, sending, supportsReadConsent, capabilitiesReady,
    streamSteps, streamingBody, streamingConversationId,
    show, newChat, send, stop, remove, rename,
  }
}

type Controller = ReturnType<typeof useCoachController>
const CoachContext = createContext<Controller | null>(null)
export function CoachProvider({ owner, children, api = coachApi }: { owner: string; children: ReactNode; api?: CoachApiClient }) {
  return <CoachOwner key={owner} owner={owner} api={api}>{children}</CoachOwner>
}
function CoachOwner({ owner, children, api }: { owner: string; children: ReactNode; api: CoachApiClient }) {
  const controller = useCoachController(owner, api)
  return <CoachContext.Provider value={controller}>{children}</CoachContext.Provider>
}
export const useCoach = () => useContext(CoachContext)
