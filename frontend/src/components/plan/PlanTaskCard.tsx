import { useTranslation } from 'react-i18next'

import type { PlanDomain, PlanTask } from '../../types'

/**
 * One plan task, as the user is allowed to see it.
 *
 * The card is deliberately literal about two things.
 *
 * A domain that may be read but not changed is labelled read-only and nothing
 * else. The model read it to reason about the plan; it did not change it, and a
 * card that said otherwise would be describing work nobody authorised.
 *
 * A candidate is only offered for confirmation when it actually passed and has not
 * expired. A button that is present but refuses is a worse answer than a card that
 * says why there is nothing to confirm.
 */
const DOMAINS: PlanDomain[] = ['training', 'diet']

const STATE_KEYS: Record<PlanTask['state'], string> = {
  collecting: 'collecting',
  awaiting_scope_permission: 'awaitingScope',
  generating: 'generating',
  repairing: 'repairing',
  awaiting_confirmation: 'awaitingConfirmation',
  awaiting_user_decision: 'awaitingUserDecision',
  activated: 'activated',
  cancelled: 'cancelled',
  expired: 'expired',
}

function expiredAt(value: string | null, now: Date): boolean {
  if (!value) return false
  const parsed = new Date(value)
  return Number.isFinite(parsed.getTime()) && parsed.getTime() <= now.getTime()
}

export interface PlanTaskCardProps {
  task: PlanTask
  onConfirm?: () => void
  onCancel?: () => void
  onAllowScope?: () => void
  onDenyScope?: () => void
  busy?: boolean
  /** Injected so a test can pin "now" instead of waiting for a real clock. */
  now?: Date
}

export function PlanTaskCard({
  task, onConfirm, onCancel, onAllowScope, onDenyScope, busy = false, now = new Date(),
}: PlanTaskCardProps) {
  const { t } = useTranslation()
  const candidate = task.candidate
  const candidateExpired = expiredAt(candidate?.expires_at ?? null, now)
  const taskExpired = expiredAt(task.expires_at, now) || task.state === 'expired'
  const passed = task.failed_domains.length === 0
  const confirmable = Boolean(
    candidate && passed && !candidateExpired && !taskExpired && task.state === 'awaiting_confirmation',
  )
  const awaitingScope = task.state === 'collecting' || task.state === 'awaiting_scope_permission'
  const closed = ['activated', 'cancelled', 'expired'].includes(task.state)

  return (
    <section className="content-panel plan-task-card" aria-label={t('plan.planTask.title')}>
      <header className="plan-task-card__header">
        <h2>{t('plan.planTask.title')}</h2>
        <span className={`plan-task-state plan-task-state--${task.state}`}>
          {t(`plan.planTask.state.${STATE_KEYS[task.state]}`)}
        </span>
      </header>

      <dl className="plan-task-card__domains">
        {DOMAINS.filter((domain) => task.read_domains.includes(domain)).map((domain) => {
          const changeable = task.change_domains.includes(domain)
          return (
            <div key={domain} className="plan-task-domain">
              <dt>{t(`plan.planTask.domain.${domain}`)}</dt>
              <dd>
                <span className={changeable ? 'plan-task-domain__changeable' : 'plan-task-domain__readonly'}>
                  {t(changeable ? 'plan.planTask.changeable' : 'plan.planTask.readOnly')}
                </span>
              </dd>
            </div>
          )
        })}
      </dl>

      <p className="plan-task-card__rounds">
        {t('plan.planTask.rounds', { used: task.repair_rounds, left: task.rounds_remaining })}
      </p>
      <p className="plan-task-card__expiry">
        {t(taskExpired ? 'plan.planTask.taskExpired' : 'plan.planTask.taskExpires', {
          at: task.expires_at,
        })}
      </p>

      {task.missing_constraints.length > 0 ? (
        <div className="plan-task-card__missing" role="status">
          <h3>{t('plan.planTask.missingConstraints')}</h3>
          <ul>{task.missing_constraints.map((path) => <li key={path}>{path}</li>)}</ul>
        </div>
      ) : null}

      {awaitingScope ? (
        <div className="plan-task-card__scope" role="group" aria-label={t('plan.planTask.scopeTitle')}>
          <p>{t('plan.planTask.scopeQuestion')}</p>
          <button type="button" disabled={busy} onClick={onAllowScope}>
            {t('plan.planTask.allowScope')}
          </button>
          <button type="button" className="secondary-button" disabled={busy} onClick={onDenyScope}>
            {t('plan.planTask.denyScope')}
          </button>
        </div>
      ) : null}

      {task.violations.length > 0 ? (
        <div className="plan-task-card__violations">
          <h3>{t('plan.planTask.violations')}</h3>
          <ul>
            {task.violations.map((violation) => (
              <li key={`${violation.code}:${violation.path}`}>
                <code>{violation.code}</code> <span>{violation.path}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="plan-task-card__candidate">
        {candidate ? (
          <>
            <p>{t('plan.planTask.candidateDigest', { digest: candidate.digest.slice(0, 12) })}</p>
            {candidate.expires_at ? (
              <p className="plan-task-card__candidate-expiry">
                {t(candidateExpired ? 'plan.planTask.candidateExpired' : 'plan.planTask.candidateExpires', {
                  at: candidate.expires_at,
                })}
              </p>
            ) : null}
            {!passed ? <p role="status">{t('plan.planTask.candidateNotPassed')}</p> : null}
            <button type="button" className="primary-button" disabled={!confirmable || busy} onClick={onConfirm}>
              {t('plan.planTask.confirm')}
            </button>
          </>
        ) : (
          <p>{t('plan.planTask.noCandidate')}</p>
        )}
      </div>

      {!closed ? (
        <button type="button" className="secondary-button" disabled={busy} onClick={onCancel}>
          {t('plan.planTask.cancel')}
        </button>
      ) : null}
    </section>
  )
}
