import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CalendarPlus,
  Check,
  CheckCircle2,
  Dumbbell,
  MessageSquarePlus,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Square,
  Trash2,
  Utensils,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'

import { ConfirmModal } from '../components/ConfirmModal'
import { CoachComposer } from '../components/coach/CoachComposer'
import { CoachMessages } from '../components/coach/CoachMessages'
import { PlanAdjustmentDialog } from '../components/plan/PlanAdjustmentDialog'
import { useChat } from '../hooks/useChat'
import { useCoach, type CoachReadDomain } from '../hooks/useCoach'
import { api } from '../services/api'
import { weeklyAutomationApi } from '../services/weeklyAutomationApi'
import type { CoachSurface } from '../types'
import { holdsCoachSlot, type CoachConversation, type CoachMessage } from '../types/coach'

const ALL_DOMAINS: CoachReadDomain[] = ['profile', 'training', 'diet']

function normalizeSurface(raw: string | null): CoachSurface {
  if (raw === 'today' || raw === 'logbook' || raw === 'review' || raw === 'plan' || raw === 'profile') {
    return raw
  }
  if (raw === 'progress') return 'review'
  return 'today'
}

type DateGroup = 'today' | 'week' | 'earlier'

function classifyConversationDate(item: CoachConversation): DateGroup {
  const stamp = Date.parse(item.updated_at || item.created_at || '')
  if (Number.isNaN(stamp)) return 'today'
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  if (stamp >= startOfToday) return 'today'
  const sevenDaysAgo = startOfToday - 6 * 24 * 60 * 60 * 1000
  if (stamp >= sevenDaysAgo) return 'week'
  return 'earlier'
}

function summarizeAnswerForFocusNote(markdown: string): string {
  return markdown
    .replace(/[#*_`>]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 400)
}

export function CoachPage() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const coach = useCoach()
  const fallbackChat = useChat()

  const initialPrompt = params.get('prompt') ?? ''
  const contextSurface = normalizeSurface(params.get('surface'))
  const contextDate = params.get('date') ?? undefined

  const [localInput, setLocalInput] = useState(initialPrompt)
  const [localDomains, setLocalDomains] = useState<CoachReadDomain[]>(['profile', 'training', 'diet'])
  const [modelStatus, setModelStatus] = useState<'unknown' | 'active' | 'unconfigured'>('unknown')
  const [activeModelName, setActiveModelName] = useState<string | null>(null)
  const [inlineHint, setInlineHint] = useState<string | null>(null)

  const [generatingPlan, setGeneratingPlan] = useState(false)
  const [generatedDraftTitle, setGeneratedDraftTitle] = useState<string | null>(null)
  const [planError, setPlanError] = useState<string | null>(null)

  const [planTask, setPlanTask] = useState<string | null | undefined>(undefined)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [deletingBusy, setDeletingBusy] = useState(false)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [renamingBusy, setRenamingBusy] = useState(false)
  const [railCollapsed, setRailCollapsed] = useState(false)

  const seededPromptRef = useRef<string>('')

  useEffect(() => {
    coach?.clearUnread?.()
  }, [coach])

  useEffect(() => {
    if (!initialPrompt || seededPromptRef.current === initialPrompt) return
    seededPromptRef.current = initialPrompt
    if (coach) {
      coach.setDraft(initialPrompt)
    } else {
      setLocalInput(initialPrompt)
    }
  }, [initialPrompt, coach])

  useEffect(() => {
    if (typeof api.modelWorkspace !== 'function') return
    let active = true
    void api.modelWorkspace()
      .then((ws) => {
        if (!active) return
        if (ws?.active?.enabled) {
          setModelStatus('active')
          setActiveModelName(ws.active.model)
        } else {
          setModelStatus('unconfigured')
          setActiveModelName(null)
        }
      })
      .catch(() => {
        if (active) setModelStatus('unknown')
      })
    return () => { active = false }
  }, [])

  const isMultiChat = Boolean(coach)
  const readDomains = coach ? coach.readDomains : localDomains
  const inputValue = coach ? coach.draft : localInput
  const setInputValue = (value: string) => {
    setInlineHint(null)
    if (coach) coach.setDraft(value)
    else setLocalInput(value)
  }

  function toggleDomain(domain: CoachReadDomain) {
    if (coach) {
      coach.toggleReadDomain(domain)
    } else {
      setLocalDomains((current) =>
        current.includes(domain)
          ? current.filter((d) => d !== domain)
          : [...current, domain],
      )
    }
  }

  const busy = coach ? (coach.sending || holdsCoachSlot(coach.active)) : fallbackChat.loading
  const sendDisabled = coach
    ? (busy || !coach.capabilitiesReady)
    : busy

  async function submitQuestion(rawText: string) {
    const trimmed = rawText.trim()
    if (!trimmed || sendDisabled) return
    setInlineHint(null)

    if (coach) {
      // Keep draft until server accepts the turn (useCoach clears draft only on success).
      if (coach.draft !== trimmed) coach.setDraft(trimmed)
      const accepted = await coach.send(
        {
          question: trimmed,
          action: 'chat',
          surface: contextSurface,
          date: contextDate,
          ...(coach.supportsReadConsent ? { read_domains: readDomains } : {}),
        },
        { openWindow: false },
      )
      if (accepted === false) {
        setInlineHint(t('coachWorkbench.sendFailedRestored'))
      }
      return
    }

    const ok = await fallbackChat.send(trimmed)
    if (ok === false) {
      setLocalInput(trimmed)
      setInlineHint(t('coachWorkbench.sendFailedRestored'))
    } else {
      setLocalInput('')
    }
  }

  async function handleGeneratePersonalizedDraft(focusNote?: string) {
    setGeneratingPlan(true)
    setPlanError(null)
    setGeneratedDraftTitle(null)
    try {
      const res = await weeklyAutomationApi.generatePersonalizedDraft({
        duration_weeks: 4,
        ...(focusNote ? { focus_note: focusNote } : {}),
      })
      setGeneratedDraftTitle(res.cycle.title)
    } catch (cause) {
      setPlanError(cause instanceof Error ? cause.message : t('planCycle.createFailed'))
    } finally {
      setGeneratingPlan(false)
    }
  }

  function handleStarterClick(prompt: string) {
    if (modelStatus === 'unconfigured') {
      setInputValue(prompt)
      setInlineHint(t('coachWorkbench.configureFirstHint'))
      return
    }
    void submitQuestion(prompt)
  }

  const quickStarters = [
    {
      key: 'progress',
      icon: Sparkles,
      label: t('coachWorkbench.starters.progressTitle'),
      prompt: t('coachWorkbench.starters.progressPrompt'),
    },
    {
      key: 'substitution',
      icon: Dumbbell,
      label: t('coachWorkbench.starters.exerciseTitle'),
      prompt: t('coachWorkbench.starters.exercisePrompt'),
    },
    {
      key: 'food',
      icon: Utensils,
      label: t('coachWorkbench.starters.foodTitle'),
      prompt: t('coachWorkbench.starters.foodPrompt'),
    },
    {
      key: 'nutrition',
      icon: Bot,
      label: t('coachWorkbench.starters.nutritionTitle'),
      prompt: t('coachWorkbench.starters.nutritionPrompt'),
    },
  ]

  const groupedConversations = useMemo(() => {
    if (!coach) return [] as Array<{ group: DateGroup; items: CoachConversation[] }>
    const buckets: Record<DateGroup, CoachConversation[]> = { today: [], week: [], earlier: [] }
    for (const conv of coach.conversations) {
      buckets[classifyConversationDate(conv)].push(conv)
    }
    return (['today', 'week', 'earlier'] as const)
      .filter((key) => buckets[key].length > 0)
      .map((group) => ({ group, items: buckets[group] }))
  }, [coach])

  const displayMessages: CoachMessage[] = useMemo(() => {
    if (coach) return coach.messages
    return fallbackChat.messages.map((msg, index) => ({
      message_id: msg.id ?? `fallback-${index}`,
      turn_id: msg.id ?? `fallback-${index}`,
      role: msg.role === 'user' ? 'user' : 'coach',
      body: msg.content,
      created_at: msg.createdAt ?? new Date().toISOString(),
      metadata: msg.role === 'agent'
        ? {
            model: msg.model,
            sources: msg.sources,
          }
        : undefined,
    }))
  }, [coach, fallbackChat.messages])

  const failedTurn = coach && coach.lastTurn?.conversation_id === coach.selected
    && ['failed', 'interrupted', 'cancelled', 'timed_out'].includes(coach.lastTurn.status)
    ? coach.lastTurn
    : null
  const retryQuestion = failedTurn && coach
    ? coach.messages.find((msg) => msg.turn_id === failedTurn.turn_id && msg.role === 'user')?.body ?? null
    : null

  const phaseText = coach
    ? coach.active?.stopping
      ? t('coachWorkbench.phaseStopping')
      : coach.active?.status === 'queued'
        ? t('coachWorkbench.phaseQueued')
        : t('coachWorkbench.phaseRunning')
    : t('coachWorkbench.phaseRunning')

  const emptyStateNode = (
    <div className="coach-wb-coldstart">
      <div className="coach-wb-coldstart-hero">
        <Bot size={28} />
        <h2>{t('coachConversation.welcome')}</h2>
        <p>{t('coachWorkbench.emptyPrompt')}</p>
      </div>
      <div className="coach-wb-starter-grid">
        {quickStarters.map(({ key, icon: Icon, label, prompt }) => (
          <button
            key={key}
            type="button"
            className="starter-card"
            disabled={busy}
            onClick={() => handleStarterClick(prompt)}
          >
            <Icon size={16} />
            <span>{label}</span>
          </button>
        ))}
      </div>
    </div>
  )

  return (
    <div className={`coach-wb-shell${railCollapsed ? ' rail-collapsed' : ''}`}>
      <ConfirmModal
        open={deletingId !== null}
        title={t('coachConversation.deleteTitle')}
        message={t('coachConversation.deleteNotice')}
        confirmLabel={t('coachConversation.stopAndDelete')}
        cancelLabel={t('coachConversation.cancel')}
        tone="danger"
        busy={deletingBusy}
        onCancel={() => { if (!deletingBusy) setDeletingId(null) }}
        onConfirm={() => {
          if (!deletingId || !coach) return
          setDeletingBusy(true)
          void coach.remove(deletingId).finally(() => {
            setDeletingBusy(false)
            setDeletingId(null)
          })
        }}
      />
      {planTask !== undefined ? (
        <PlanAdjustmentDialog open taskId={planTask ?? undefined} onClose={() => setPlanTask(undefined)} />
      ) : null}

      {/* Left Sidebar: New Chat + Grouped History + Quick Tools */}
      <aside className={`coach-wb-rail${railCollapsed ? ' collapsed' : ''}`}>
        <div className="coach-wb-rail-header">
          <button
            type="button"
            className="primary-button coach-wb-newchat-btn"
            aria-label={t('coachConversation.newChat')}
            title={t('coachConversation.newChat')}
            disabled={busy}
            onClick={() => {
              if (coach) coach.newChat({ openWindow: false })
              else fallbackChat.clear?.()
              setInlineHint(null)
            }}
          >
            <MessageSquarePlus size={16} />
            {!railCollapsed ? t('coachConversation.newChat') : null}
          </button>
          <button
            type="button"
            className="icon-button coach-wb-collapse-btn"
            aria-label={t(railCollapsed ? 'coachWorkbench.expandSidebar' : 'coachWorkbench.collapseSidebar')}
            aria-expanded={!railCollapsed}
            title={t(railCollapsed ? 'coachWorkbench.expandSidebar' : 'coachWorkbench.collapseSidebar')}
            onClick={() => setRailCollapsed((prev) => !prev)}
          >
            {railCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </div>

        {!railCollapsed && isMultiChat && coach ? (
          <nav className="coach-wb-history" aria-label={t('coachConversation.history')}>
            {groupedConversations.length === 0 ? (
              <p className="muted-copy coach-wb-empty-history">{t('coachWorkbench.noConversations')}</p>
            ) : (
              groupedConversations.map(({ group, items }) => (
                <div key={group} className="coach-wb-history-group">
                  <span className="coach-wb-group-label">
                    {t(group === 'today'
                      ? 'coachWorkbench.groupToday'
                      : group === 'week'
                        ? 'coachWorkbench.groupWeek'
                        : 'coachWorkbench.groupEarlier')}
                  </span>
                  <ul className="coach-conv-list">
                    {items.map((conv) => (
                      <li
                        key={conv.conversation_id}
                        className={coach.selected === conv.conversation_id ? 'active' : ''}
                      >
                        {renamingId === conv.conversation_id ? (
                          <form
                            className="coach-rename-form"
                            onSubmit={(event) => {
                              event.preventDefault()
                              if (renamingBusy || !renameDraft.trim()) return
                              setRenamingBusy(true)
                              void coach.rename(conv.conversation_id, renameDraft.trim()).finally(() => {
                                setRenamingBusy(false)
                                setRenamingId(null)
                              })
                            }}
                          >
                            <input
                              aria-label={t('coachConversation.chatTitle')}
                              autoFocus
                              maxLength={120}
                              value={renameDraft}
                              onChange={(event) => setRenameDraft(event.target.value)}
                            />
                            <button type="submit" className="icon-button" disabled={renamingBusy} aria-label={t('coachConversation.save')}>
                              <Check size={14} />
                            </button>
                            <button type="button" className="icon-button" onClick={() => setRenamingId(null)} aria-label={t('coachConversation.cancel')}>
                              <X size={14} />
                            </button>
                          </form>
                        ) : (
                          <>
                            <button
                              type="button"
                              className="conv-select-btn"
                              aria-current={coach.selected === conv.conversation_id ? 'true' : undefined}
                              onClick={() => coach.setSelected(conv.conversation_id)}
                            >
                              {conv.title || t('coachConversation.newChat')}
                            </button>
                            <div className="conv-row-actions">
                              <button
                                type="button"
                                className="icon-button"
                                aria-label={t('coachConversation.rename')}
                                onClick={() => {
                                  setRenamingId(conv.conversation_id)
                                  setRenameDraft(conv.title ?? '')
                                }}
                              >
                                <Pencil size={13} />
                              </button>
                              <button
                                type="button"
                                className="icon-button"
                                aria-label={t('coachConversation.delete')}
                                onClick={() => setDeletingId(conv.conversation_id)}
                              >
                                <Trash2 size={13} />
                              </button>
                            </div>
                          </>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ))
            )}
          </nav>
        ) : null}

        {!railCollapsed ? (
          <section className="coach-wb-tools">
            <span className="coach-wb-group-label">{t('coachWorkbench.quickTools')}</span>
            <button
              type="button"
              className="secondary-button coach-wb-tool-btn"
              disabled={generatingPlan}
              onClick={() => void handleGeneratePersonalizedDraft()}
            >
              <CalendarPlus size={15} />
              {generatingPlan ? t('common.generating') : t('coachWorkbench.generatePlanDraft')}
            </button>
            <small className="muted-copy">{t('coachWorkbench.planActionDesc')}</small>
          </section>
        ) : null}
      </aside>

      {/* Right Main Chat Column: Fixed Header + Scrollable Messages + Pinned Composer */}
      <section className="coach-wb-main" aria-label={t('coachConversation.messages')}>
        <header className="coach-wb-header">
          <div className="coach-wb-header-top">
            <div className="coach-wb-title-row">
              <h1>{t('coachWorkbench.title')}</h1>
              {modelStatus === 'active' && activeModelName ? (
                <span className="coach-model-pill active">
                  <span className="status-dot" />
                  {activeModelName}
                  <Link className="text-link" to="/settings/model?returnTo=/coach">
                    {t('coachWorkbench.switchModel')}
                  </Link>
                </span>
              ) : null}
            </div>
            <div className="session-scope-bar" aria-label={t('coachWorkbench.readScopeLabel')}>
              <span className="scope-label">
                <ShieldCheck size={14} />
                {t('coachWorkbench.sessionScope')}:
              </span>
              {ALL_DOMAINS.map((domain) => {
                const enabled = readDomains.includes(domain)
                return (
                  <button
                    key={domain}
                    type="button"
                    className={`chip-toggle ${enabled ? 'selected' : ''}`}
                    aria-pressed={enabled}
                    disabled={busy}
                    onClick={() => toggleDomain(domain)}
                  >
                    {t(`coachWorkbench.domains.${domain}`)} {enabled ? '✓' : ''}
                  </button>
                )
              })}
              <small className="muted-copy">{t('coachWorkbench.scopeRevokeHint')}</small>
            </div>
          </div>

          {modelStatus === 'unconfigured' ? (
            <div className="coach-model-guide-banner" role="status">
              <div className="coach-model-guide-copy">
                <AlertTriangle size={16} />
                <span>{t('coachWorkbench.modelUnconfiguredBanner')}</span>
              </div>
              <Link className="primary-button compact-btn" to="/settings/model?returnTo=/coach">
                {t('coachWorkbench.configureModel')}
                <ArrowRight size={14} />
              </Link>
            </div>
          ) : null}
        </header>

        <div className="coach-wb-messages">
          <CoachMessages
            messages={displayMessages}
            conversation={coach ? coach.selected : 'single'}
            visible
            onOpenTask={setPlanTask}
            onGeneratePlanFromAnswer={(body) => void handleGeneratePersonalizedDraft(summarizeAnswerForFocusNote(body))}
            generatingPlan={generatingPlan}
            streamSteps={coach && coach.selected === coach.streamingConversationId ? coach.streamSteps : []}
            streamingBody={coach && coach.selected === coach.streamingConversationId ? coach.streamingBody : ''}
            streamingActive={Boolean(coach && busy && coach.selected === coach.streamingConversationId)}
            emptyState={emptyStateNode}
          />
        </div>

        {/* Inline Receipt / Execution Status / Error Recovery */}
        <div className="coach-wb-footer-stack">
          {generatedDraftTitle ? (
            <div className="coach-inline-receipt" role="status">
              <div className="coach-inline-receipt-copy">
                <CheckCircle2 size={16} />
                <strong>{t('coachWorkbench.draftCreated', { title: generatedDraftTitle })}</strong>
              </div>
              <div className="coach-inline-receipt-actions">
                <Link className="primary-button compact-btn" to="/plan">
                  {t('weeklyAutomation.reviewDraft')}
                  <ArrowRight size={14} />
                </Link>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={t('weeklyAutomation.dismiss')}
                  onClick={() => setGeneratedDraftTitle(null)}
                >
                  <X size={14} />
                </button>
              </div>
            </div>
          ) : null}

          {planError ? (
            <div className="coach-inline-alert" role="alert">
              <span>{planError}</span>
            </div>
          ) : null}

          {busy ? (
            <div className="coach-wb-phase-bar" role="status">
              <span>{phaseText}</span>
              <div className="coach-wb-phase-actions">
                {coach && coach.active && coach.active.conversation_id !== coach.selected ? (
                  <button
                    type="button"
                    className="secondary-button compact-btn"
                    onClick={() => coach.setSelected(coach.active!.conversation_id)}
                  >
                    {t('coachConversation.goActive')}
                  </button>
                ) : null}
                <button
                  type="button"
                  className="secondary-button compact-btn"
                  disabled={coach ? Boolean(coach.active?.stopping) : false}
                  onClick={() => {
                    if (coach) void coach.stop()
                    else fallbackChat.stop?.()
                  }}
                >
                  <Square size={13} />
                  {t('coachConversation.stop')}
                </button>
              </div>
            </div>
          ) : null}

          {coach && coach.notice ? (
            <div className="coach-wb-notice" role="status">{coach.notice}</div>
          ) : null}

          {coach && failedTurn && retryQuestion ? (
            <div className="coach-wb-recovery" role="status">
              <div>
                <strong>{t(`coachConversation.states.${failedTurn.status}`)}</strong>
                <small>{t('coachConversation.retryNotice')}</small>
              </div>
              <div className="coach-wb-phase-actions">
                <button
                  type="button"
                  className="secondary-button compact-btn"
                  onClick={() => coach.setDraft(retryQuestion)}
                >
                  {t('coachConversation.editQuestion')}
                </button>
                {failedTurn.receipt?.context ? (
                  <button
                    type="button"
                    className="primary-button compact-btn"
                    disabled={sendDisabled}
                    onClick={() => {
                      const ctx = failedTurn.receipt!.context!
                      void coach.send(
                        {
                          question: retryQuestion,
                          action: ctx.action,
                          surface: ctx.surface,
                          date: ctx.date ?? undefined,
                          plan_id: ctx.plan_id ?? undefined,
                          report_week: ctx.report_week ?? undefined,
                          language: ctx.language,
                          answer_mode: ctx.answer_mode,
                          ...(ctx.action === 'chat' && coach.supportsReadConsent ? { read_domains: readDomains } : {}),
                        },
                        { openWindow: false },
                      )
                    }}
                  >
                    <RotateCcw size={13} />
                    {t('coachConversation.retry')}
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}

          {((!isMultiChat && fallbackChat.error) || (isMultiChat && coach?.error) || inlineHint) ? (
            <div className="coach-inline-alert" role="alert">
              <span>
                {!isMultiChat && fallbackChat.error
                  ? fallbackChat.error
                  : isMultiChat && coach?.error
                    ? t('coachConversation.error')
                    : inlineHint}
              </span>
              {!isMultiChat && fallbackChat.lastFailedQuestion ? (
                <button
                  type="button"
                  className="secondary-button compact-btn"
                  disabled={busy}
                  onClick={() => void submitQuestion(fallbackChat.lastFailedQuestion!)}
                >
                  <RotateCcw size={13} />
                  {t('coachWorkbench.retryLast')}
                </button>
              ) : null}
            </div>
          ) : null}

          <CoachComposer
            inputId="coach-workbench-question"
            value={inputValue}
            onChange={setInputValue}
            disabled={sendDisabled}
            placeholder={t('components.chatPlaceholder')}
            onSend={() => void submitQuestion(inputValue)}
          />
        </div>
      </section>
    </div>
  )
}
