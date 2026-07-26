import {
  ArrowLeft,
  Check,
  Sparkles,
  Trash2,
  WandSparkles,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { SmartCandidateEditor } from '../components/smart-entry/SmartCandidateEditor'
import { useAuth } from '../hooks/useAuth'
import { useSmartEntryDraft } from '../hooks/useSmartEntryDraft'
import type {
  SmartCandidate,
  SmartEntryDraftPayload,
} from '../types/smartEntry'


export function SmartEntry() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [params] = useSearchParams()
  const [logDate, setLogDate] = useState(
    () => validDate(params.get('date')) ?? browserDate(),
  )
  const [rawText, setRawText] = useState('')
  const [candidates, setCandidates] = useState<SmartCandidate[]>([])
  const ownerId = user?.user_id ?? 'anonymous'
  const recoveryKey = `fitlife:smart-entry:${ownerId}:${logDate}`
  const draft = useSmartEntryDraft(recoveryKey)
  const selected = candidates.filter((candidate) => candidate.selected)
  const unresolved = candidates.some((candidate) => (
    candidate.issues.some(
      (issue) => issue !== 'SMART_ENTRY_AGENT_ESTIMATE_ACCEPTANCE_REQUIRED',
    )
  ))
  const canConfirm = selected.length > 0
    && selected.every((candidate) => candidate.issues.length === 0)
  const busy = ['restoring', 'parsing', 'saving', 'analyzing', 'confirming']
    .includes(draft.status)

  useEffect(() => {
    let active = true
    void draft.restore(logDate).then((restored) => {
      if (!active || !restored) return
      setRawText(restored.payload.raw_text)
      setCandidates(restored.payload.candidates)
    }).catch(() => {
      // The hook exposes the recoverable error.
    })
    return () => {
      active = false
    }
    // Restore only when the account/date recovery scope changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recoveryKey, logDate])

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
      navigate(`/?date=${encodeURIComponent(logDate)}`, { replace: true })
    } catch {
      // Recovery metadata remains available for explicit retry.
    }
  }

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
              placeholder={t('smartEntry.placeholder')}
              onChange={(event) => setRawText(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="primary-button"
            disabled={busy || !rawText.trim()}
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
            <p className="form-error" role="alert">{draft.error}</p>
          ) : null}
          {draft.status === 'conflict' ? (
            <p className="form-error">{t('smartEntry.conflict')}</p>
          ) : null}

          {candidates.length ? (
            <div className="smart-candidate-list">
              {candidates.map((candidate) => (
                <SmartCandidateEditor
                  key={candidate.id}
                  candidate={candidate}
                  onChange={(next) => setCandidates((current) => (
                    current.map((item) => item.id === next.id ? next : item)
                  ))}
                />
              ))}
            </div>
          ) : (
            <div className="smart-entry-empty">
              <WandSparkles size={22} />
              <strong>{t('smartEntry.empty')}</strong>
              <span>{t('smartEntry.emptyAction')}</span>
            </div>
          )}

          {candidates.length ? (
            <footer className="smart-review-actions">
              <button
                type="button"
                className="secondary-button"
                disabled={busy || !unresolved || !payload}
                onClick={() => void analyze()}
              >
                <WandSparkles size={17} />
                {draft.status === 'analyzing'
                  ? t('smartEntry.analyzing')
                  : t('smartEntry.analyze')}
              </button>
              <button
                type="button"
                className="primary-button"
                disabled={busy || !canConfirm || !payload}
                onClick={() => void confirm()}
              >
                <Check size={17} />
                {draft.status === 'confirming'
                  ? t('smartEntry.confirming')
                  : t('smartEntry.confirm')}
              </button>
            </footer>
          ) : null}
        </section>
      </div>
    </div>
  )
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
