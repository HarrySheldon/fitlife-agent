import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../../services/api'
import type { PlanDomain, PlanTask } from '../../types'
import { PlanTaskCard } from './PlanTaskCard'

/**
 * The one place a plan adjustment is started, run and confirmed.
 *
 * Three rules are visible in the shape of this component.
 *
 * *Nothing runs by itself.* Opening the dialog, refreshing it or receiving a task
 * from the server never calls ``execute`` or ``confirm``. A model call costs
 * money and a confirmation writes history, so both happen only on a click.
 *
 * *Every action keeps its key.* A retry after an unknown network result reuses
 * the key the attempt started with, so the server recognises it as the same
 * request instead of refusing it as a version conflict.
 *
 * *Reading is not changing.* The scope boxes grant change permission per domain.
 * A domain left unticked is read so the model can reason, and the card says it is
 * read-only rather than pretending it was adjusted.
 */
const ALL_DOMAINS: PlanDomain[] = ['training', 'diet']

export interface PlanAdjustmentDialogProps {
  open: boolean
  onClose: () => void
  /** The plan the task is based on. Resolved from the server when absent. */
  planId?: string
  onConfirmed?: (planId: string) => void
  now?: Date
}

export function PlanAdjustmentDialog({
  open, onClose, planId, onConfirmed, now,
}: PlanAdjustmentDialogProps) {
  const { t } = useTranslation()
  const [instructions, setInstructions] = useState('')
  const [changeDomains, setChangeDomains] = useState<PlanDomain[]>(ALL_DOMAINS)
  const [task, setTask] = useState<PlanTask | null>(null)
  const [answer, setAnswer] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmedPlanId, setConfirmedPlanId] = useState<string | null>(null)
  const keys = useRef<Record<string, string>>({})
  const counter = useRef(0)

  useEffect(() => {
    if (open) return
    // Closing forgets the task, not the account's state: the task is persisted,
    // and reopening starts from what the server says rather than from a stale
    // copy this component happened to keep.
    setTask(null); setError(null); setConfirmedPlanId(null); setBusy(false)
    setAnswer(null)
    keys.current = {}
  }, [open])

  function keyFor(action: string): string {
    const existing = keys.current[action]
    if (existing) return existing
    counter.current += 1
    const created = `${action}-${counter.current}`
    keys.current[action] = created
    return created
  }

  async function run<T>(action: string, work: () => Promise<T>): Promise<T | null> {
    setBusy(true); setError(null)
    try {
      return await work()
    } catch (err) {
      setError((err as Error).message)
      // The key is kept: the user retries the same attempt, not a new one.
      return null
    } finally {
      setBusy(false)
    }
  }

  async function start() {
    const text = instructions.trim()
    if (!text) return
    const baseId = planId ?? (await run('resolve', async () => (await api.getCurrentPlan()).plan.plan_id))
    if (!baseId) return
    const started = await run('start', () => api.startPlanTask({
      base_plan_id: baseId,
      read_domains: ALL_DOMAINS,
      change_domains: changeDomains,
      instructions: text,
    }, keyFor('start')))
    if (started) setTask(started)
  }

  async function decide(decision: 'allow' | 'deny') {
    if (!task) return
    const next = await run(`scope-${decision}`, () => api.decidePlanTaskScope(task.task_id, {
      expected_version: task.version,
      read_domains: ALL_DOMAINS,
      change_domains: decision === 'allow' ? ALL_DOMAINS : task.change_domains,
      decision,
    }, keyFor(`scope-${decision}`)))
    if (next) setTask(next)
  }

  async function execute() {
    if (!task) return
    const text = instructions.trim()
    if (!text) return
    const result = await run('execute', () => api.executePlanTask(task.task_id, {
      expected_version: task.version,
      instructions: text,
    }, keyFor('execute')))
    if (result) { setTask(result.task); setAnswer(result.answer) }
  }

  async function confirm() {
    if (!task?.candidate) return
    const result = await run('confirm', () => api.confirmPlanTask(task.task_id, {
      expected_version: task.version,
      expected_head_revision: task.base_head_revision,
      candidate_digest: task.candidate!.digest,
    }, keyFor('confirm')))
    if (!result) return
    setTask(result.task)
    setConfirmedPlanId(result.plan.plan_id)
    onConfirmed?.(result.plan.plan_id)
  }

  async function cancel() {
    if (!task) return
    const next = await run('cancel', () => api.cancelPlanTask(task.task_id, {
      expected_version: task.version,
    }, keyFor('cancel')))
    if (next) setTask(next)
  }

  if (!open) return null

  return (
    <div className="plan-adjustment-dialog" role="dialog" aria-modal="true"
         aria-label={t('plan.planTask.dialogTitle')}>
      <header className="plan-adjustment-dialog__header">
        <h2>{t('plan.planTask.dialogTitle')}</h2>
        <button type="button" className="secondary-button" onClick={onClose}>
          {t('plan.planTask.close')}
        </button>
      </header>

      {error ? <p className="plan-adjustment-dialog__error" role="alert">{error}</p> : null}
      {confirmedPlanId ? (
        <p role="status">{t('plan.planTask.confirmed', { planId: confirmedPlanId })}</p>
      ) : null}

      {!task ? (
        <section className="content-panel">
          <label htmlFor="plan-task-instructions">{t('plan.instructions')}</label>
          <textarea id="plan-task-instructions" value={instructions}
                    placeholder={t('plan.instructionsPlaceholder')}
                    onChange={(event) => setInstructions(event.target.value)} />
          <fieldset className="plan-adjustment-dialog__scope">
            <legend>{t('plan.planTask.scopeLegend')}</legend>
            {ALL_DOMAINS.map((domain) => (
              <label key={domain}>
                <input type="checkbox" checked={changeDomains.includes(domain)}
                       onChange={(event) => setChangeDomains((current) => (
                         event.target.checked
                           ? ALL_DOMAINS.filter((item) => current.includes(item) || item === domain)
                           : current.filter((item) => item !== domain)
                       ))} />
                {t(`plan.planTask.domain.${domain}`)}
              </label>
            ))}
          </fieldset>
          <button type="button" className="primary-button" disabled={busy || !instructions.trim()}
                  onClick={() => void start()}>
            {t('plan.planTask.start')}
          </button>
        </section>
      ) : (
        <>
          <PlanTaskCard task={task} busy={busy} now={now}
                        onAllowScope={() => void decide('allow')}
                        onDenyScope={() => void decide('deny')}
                        onConfirm={() => void confirm()}
                        onCancel={() => void cancel()} />
          {answer ? (
            // The model's prose is shown beside the deterministic failures, never
            // merged into them: a sentence about what changed is not evidence that
            // anything valid did.
            <section className="content-panel plan-adjustment-dialog__explanation">
              <h3>{t('plan.planTask.explanation')}</h3>
              <p>{answer}</p>
            </section>
          ) : null}
          {task.state !== 'awaiting_confirmation' && task.state !== 'activated' ? (
            <button type="button" className="primary-button" disabled={busy || !instructions.trim()}
                    onClick={() => void execute()}>
              {t('plan.planTask.execute')}
            </button>
          ) : null}
        </>
      )}
    </div>
  )
}
