import {
  ArrowLeft,
  Check,
  Sparkles,
  Trash2,
  WandSparkles,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { normalizeCandidate, SmartCandidateEditor } from '../components/smart-entry/SmartCandidateEditor'
import { ClarificationPanel } from '../components/smart-entry/ClarificationPanel'
import { EntryItemCard } from '../components/smart-entry/EntryItemCard'
import { smartEntryApi } from '../services/smartEntryApi'
import { useAuth } from '../hooks/useAuth'
import { useSmartEntryDraft } from '../hooks/useSmartEntryDraft'
import type {
  SmartCandidate,
  SmartEntryDraftPayload,
  EntryCapabilities,
} from '../types/smartEntry'


export function SmartEntry() {
  const { user } = useAuth()
  const [params] = useSearchParams()
  const [logDate, setLogDate] = useState(
    () => validDate(params.get('date')) ?? browserDate(),
  )
  const ownerId = user?.user_id ?? 'anonymous'
  return <SmartEntryWorkspace key={`${ownerId}:${logDate}`} ownerId={ownerId} logDate={logDate} setLogDate={setLogDate} />
}

function SmartEntryWorkspace({ ownerId, logDate, setLogDate }: { ownerId: string; logDate: string; setLogDate: (date: string) => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [rawText, setRawText] = useState('')
  const [candidates, setCandidates] = useState<SmartCandidate[]>([])
  const candidatesRef = useRef(candidates)
  candidatesRef.current = candidates
  const previousServer = useRef<SmartCandidate[]>([])
  const [trainingConflict, setTrainingConflict] = useState(false)
  const [capabilities, setCapabilities] = useState<EntryCapabilities | null>(null)
  const [selectedItems, setSelectedItems] = useState<Record<string, number>>({})
  const [acceptedItems, setAcceptedItems] = useState<Record<string, number>>({})
  const [restoredAt, setRestoredAt] = useState<string | null>(null)
  const recoveryKey = `fitlife:smart-entry:${ownerId}:${logDate}`
  const draft = useSmartEntryDraft(recoveryKey)
  const interaction = draft.draft?.payload.interaction
  const active = interaction?.active === true
  const selected = candidates.filter((candidate) => candidate.selected && (!active || candidate.kind !== 'food'))
  const unresolved = candidates.some((candidate) => (
    candidate.issues.some(
      (issue) => issue !== 'SMART_ENTRY_AGENT_ESTIMATE_ACCEPTANCE_REQUIRED',
    )
  ))
  const canConfirm = !trainingConflict && selected.length > 0
    && selected.every((candidate) => candidate.issues.length === 0)
  const busy = ['restoring', 'parsing', 'saving', 'analyzing', 'confirming']
    .includes(draft.status)

  useEffect(() => {
    let live = true
    setCapabilities(null)
    void smartEntryApi.capabilities().then((value) => { if (live) setCapabilities(value) }).catch(() => { /* Legacy flow remains available. */ })
    return () => { live = false }
  }, [ownerId])

  useEffect(() => {
    let active = true
    setRawText(''); setCandidates([]); setSelectedItems({}); setAcceptedItems({}); setRestoredAt(null)
    void draft.restore(logDate).then((restored) => {
      if (!active || !restored) return
      setRawText(restored.payload.raw_text)
      setCandidates(restored.payload.candidates)
      setRestoredAt(restored.updated_at)
    }).catch(() => {
      // The hook exposes the recoverable error.
    })
    return () => {
      active = false
    }
    // Restore only when the account/date recovery scope changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recoveryKey, logDate])

  useEffect(() => {
    if (!draft.draft) {
      previousServer.current = []
      setCandidates([]); setRawText(''); setTrainingConflict(false)
      return
    }
    if (!draft.draft?.payload.interaction?.active) return
    const prior = new Map(previousServer.current.map((item) => [item.id, item]))
    const local = new Map(candidatesRef.current.map((item) => [item.id, item]))
    let conflict = false
    const next = draft.draft.payload.candidates.map((server) => {
      if (draft.draftSource === 'training_save') return server
      const baseline = prior.get(server.id)
      const edited = local.get(server.id)
      if (!baseline || !edited || baseline.kind !== server.kind || edited.kind !== server.kind
        || (server.kind !== 'strength' && server.kind !== 'cardio')) return server
      const merged = mergeTrainingEdits(baseline, edited, server)
      conflict ||= merged.conflict
      return merged.candidate
    })
    previousServer.current = draft.draft.payload.candidates
    setCandidates(next)
    setTrainingConflict((current) => draft.draftSource === 'training_save' ? false : current || conflict)
    const valid = new Map(draft.draft.payload.interaction.items.filter((item) => item.state === 'ready').map((item) => [item.item_id, item.revision]))
    setSelectedItems((current) => Object.fromEntries(Object.entries(current).filter(([id, revision]) => valid.get(id) === revision)))
    setAcceptedItems((current) => Object.fromEntries(Object.entries(current).filter(([id, revision]) => valid.get(id) === revision)))
  }, [draft.draft, draft.draftSource])

  const payload = useMemo<SmartEntryDraftPayload | null>(() => {
    if (!draft.draft) return null
    return {
      log_date: logDate,
      raw_text: rawText,
      parser_version: draft.draft.payload.parser_version,
      candidates,
    }
  }, [candidates, draft.draft, logDate, rawText])

  async function parse() {
    if (!rawText.trim()) return
    try {
      const created = await draft.parse({
        log_date: logDate,
        raw_text: rawText,
      })
      setCandidates(created.payload.candidates)
    } catch {
      // Draft state and source text remain available for retry.
    }
  }

  async function analyze() {
    if (!payload || !unresolved) return
    try {
      const analyzed = await draft.analyze(payload)
      setCandidates(analyzed.payload.candidates)
    } catch {
      // Deterministic candidates and local edits are intentionally preserved.
    }
  }

  async function confirm() {
    if (!payload || !canConfirm) return
    try {
      await draft.confirm(payload)
      if (!active) navigate(`/?date=${encodeURIComponent(logDate)}`, { replace: true })
    } catch {
      // Recovery metadata remains available for explicit retry.
    }
  }

  async function saveItems() {
    if (!interaction) return
    const selections = interaction.items.filter((item) => item.state === 'ready' && selectedItems[item.item_id] === item.revision)
      .filter((item) => !draft.draft?.dependency_validity?.some((dependency) => dependency.item_id === item.item_id && !dependency.valid))
      .map((item) => ({ item_id: item.item_id, item_revision: item.revision }))
    const estimates = selections.filter((item) => acceptedItems[item.item_id] === item.item_revision)
    try { await draft.confirmItems(selections, estimates) } catch { /* Explicit retry preserves the same command. */ }
  }
  const readySelections = interaction?.items.filter((item) => item.state === 'ready' && selectedItems[item.item_id] === item.revision) ?? []
  const canSaveItems = readySelections.length > 0 && readySelections.every((item) => (
    !draft.draft?.dependency_validity?.some((dependency) => dependency.item_id === item.item_id && !dependency.valid)
    && (!Object.values(item.sources).includes('estimated') || acceptedItems[item.item_id] === item.revision)
  ))

  async function discard() {
    try {
      await draft.discard()
      setCandidates([])
      setRawText('')
    } catch {
      // Keep the visible state when deletion fails.
    }
  }

  return (
    <div className="page-stack smart-entry-page">
      <header className="smart-entry-header">
        <button
          type="button"
          className="icon-button"
          aria-label={t('smartEntry.back')}
          title={t('smartEntry.back')}
          onClick={() => navigate(`/?date=${encodeURIComponent(logDate)}`)}
        >
          <ArrowLeft size={19} />
        </button>
        <div>
          <span>{t('smartEntry.eyebrow')}</span>
          <h1>{t('smartEntry.title')}</h1>
        </div>
        <label>
          <span>{t('smartEntry.date')}</span>
          <input
            type="date"
            value={logDate}
            onChange={(event) => setLogDate(event.target.value)}
          />
        </label>
      </header>

      <div className="smart-entry-workspace">
        <section className="smart-source-pane">
          <div>
            <WandSparkles size={18} />
            <h2>{t('smartEntry.sourceTitle')}</h2>
          </div>
          <label>
            <span>{t('smartEntry.sourceLabel')}</span>
            <textarea
              rows={12}
              value={rawText}
              disabled={active}
              placeholder={t('smartEntry.placeholder')}
              onChange={(event) => setRawText(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="primary-button"
            disabled={busy || active || !rawText.trim()}
            onClick={() => void parse()}
          >
            <Sparkles size={17} />
            {draft.status === 'parsing'
              ? t('smartEntry.parsing')
              : t('smartEntry.parse')}
          </button>
          {draft.draft ? (
            <button
              type="button"
              className="text-button destructive-text"
              disabled={busy}
              onClick={() => void discard()}
            >
              <Trash2 size={16} />
              {t('smartEntry.discard')}
            </button>
          ) : null}
        </section>

        <section className="smart-review-pane" aria-labelledby="smart-review-title">
          <header>
            <div>
              <span>{t('smartEntry.reviewEyebrow')}</span>
              <h2 id="smart-review-title">{t('smartEntry.reviewTitle')}</h2>
            </div>
            {candidates.length ? (
              <span>{t('smartEntry.candidateCount', {
                count: candidates.length,
              })}</span>
            ) : null}
          </header>

          {draft.error ? (
            <p className="form-error" role="alert">{draft.error === 'SMART_ENTRY_TASK_UNAVAILABLE' ? t('smartInteraction.unavailable') : draft.error === 'SMART_ENTRY_RECOVERY_REVIEW_REQUIRED' ? t('smartInteraction.reviewRequired') : draft.error}</p>
          ) : null}
          {draft.status === 'conflict' ? (
            <p className="form-error">{t('smartEntry.conflict')}</p>
          ) : null}
          {trainingConflict ? <div>
            <p className="form-error" role="alert">{t('smartInteraction.trainingConflict')}</p>
            <button type="button" className="secondary-button" disabled={busy} onClick={() => {
              setCandidates(draft.draft?.payload.candidates ?? [])
              setTrainingConflict(false)
            }}>{t('smartInteraction.reloadTraining')}</button>
          </div> : null}

          {restoredAt ? <p className="smart-recovery-note" role="status">{t('smartInteraction.recovered', { date: new Date(restoredAt).toLocaleString() })}</p> : null}
          {capabilities?.interactive_entry_enabled && draft.draft && !active && candidates.some((item) => item.kind === 'food') ? <button type="button" className="secondary-button" disabled={busy}
            onClick={() => { void draft.startInteraction().catch(() => {}) }}>{t('smartInteraction.start')}</button> : null}
          {active && interaction ? <>
            {!capabilities?.interactive_entry_enabled ? <p role="status">{t('smartInteraction.disabled')}</p> : null}
            <ClarificationPanel interaction={interaction} busy={busy} disabled={!capabilities?.interactive_entry_enabled} onAnswer={draft.answerInteraction} />
            <div className="smart-candidate-list">{interaction.items.map((item) => <EntryItemCard key={item.item_id} item={item}
              candidate={candidates.find((candidate) => candidate.id === item.item_id)}
              commit={draft.draft?.item_commits?.find((commit) => commit.item_id === item.item_id)}
              dependencyValid={!draft.draft?.dependency_validity?.some((dependency) => dependency.item_id === item.item_id && !dependency.valid)}
              logDate={logDate} busy={busy} enabled={!!capabilities?.interactive_entry_enabled}
              selected={selectedItems[item.item_id] === item.revision} accepted={acceptedItems[item.item_id] === item.revision}
              onSelect={(value) => setSelectedItems((current) => { const next = { ...current }; if (value) next[item.item_id] = item.revision; else delete next[item.item_id]; return next })}
              onAccept={(value) => setAcceptedItems((current) => { const next = { ...current }; if (value) next[item.item_id] = item.revision; else delete next[item.item_id]; return next })}
              onCorrect={(updates) => draft.correctItem(item.item_id, item.revision, updates)} />)}</div>
            <button type="button" className="primary-button" disabled={busy || !capabilities?.interactive_entry_enabled || !canSaveItems}
              onClick={() => void saveItems()}>{t('smartInteraction.saveSelected')}</button>
          </> : null}

          {candidates.length ? (
            <div className="smart-candidate-list">
              {candidates.filter((candidate) => !active || candidate.kind !== 'food').map((candidate) => (
                <fieldset key={candidate.id} disabled={busy || (active && candidate.kind !== 'strength' && candidate.kind !== 'cardio')} className="smart-legacy-candidate">
                <SmartCandidateEditor
                  candidate={candidate}
                  lockKind={active}
                  onChange={(next) => setCandidates((current) => (
                    current.map((item) => item.id === next.id ? next : item)
                  ))}
                />
                </fieldset>
              ))}
            </div>
          ) : (
            <div className="smart-entry-empty">
              <WandSparkles size={22} />
              <strong>{t('smartEntry.empty')}</strong>
              <span>{t('smartEntry.emptyAction')}</span>
            </div>
          )}

          {candidates.some((candidate) => !active || candidate.kind !== 'food') ? (
            <footer className="smart-review-actions">
              {!active ? <button
                type="button"
                className="secondary-button"
                disabled={busy || !unresolved || !payload}
                onClick={() => void analyze()}
              >
                <WandSparkles size={17} />
                {draft.status === 'analyzing'
                  ? t('smartEntry.analyzing')
                  : t('smartEntry.analyze')}
              </button> : null}
              <button
                type="button"
                className="primary-button"
                disabled={busy || !canConfirm || !payload}
                onClick={() => void confirm()}
              >
                <Check size={17} />
                {draft.status === 'confirming'
                  ? t('smartEntry.confirming')
                  : t(active ? 'smartInteraction.confirmTraining' : 'smartEntry.confirm')}
              </button>
            </footer>
          ) : null}
        </section>
      </div>
    </div>
  )
}

function sameField(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object' || Array.isArray(left) !== Array.isArray(right)) return false
  const a = Object.entries(left).sort(([key], [other]) => key.localeCompare(other))
  const b = Object.entries(right).sort(([key], [other]) => key.localeCompare(other))
  return a.length === b.length && a.every(([key, value], index) => key === b[index][0] && sameField(value, b[index][1]))
}

function mergeTrainingEdits(baseline: SmartCandidate, local: SmartCandidate, server: SmartCandidate) {
  let conflict = false
  const merge = <T,>(before: T, edited: T, current: T): T => {
    if (sameField(before, edited) || sameField(edited, current)) return current
    if (!sameField(before, current)) conflict = true
    return edited
  }
  const values = { ...server.values }
  for (const key of Object.keys(local.values)) {
    values[key] = merge(baseline.values[key], local.values[key], server.values[key])
  }
  const candidate = {
    ...server, values,
    selected: merge(baseline.selected, local.selected, server.selected),
    selected_catalog_id: merge(baseline.selected_catalog_id, local.selected_catalog_id, server.selected_catalog_id),
    agent_estimate_accepted: merge(baseline.agent_estimate_accepted, local.agent_estimate_accepted, server.agent_estimate_accepted),
    issues: sameField(baseline, server) ? local.issues : server.issues,
  }
  return { candidate: normalizeCandidate(candidate), conflict }
}

function validDate(value: string | null): string | null {
  return value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null
}

function browserDate(): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const values = Object.fromEntries(
    parts.map(({ type, value }) => [type, value]),
  )
  return `${values.year}-${values.month}-${values.day}`
}
