import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ErrorState } from '../components/ErrorState'
import { MetricCard } from '../components/MetricCard'
import { api } from '../services/api'
import type { EvalGroupMetric, EvalResult } from '../types'
import { evaluationLabelKey, failureSummary, formatRate } from './evaluationViewModel'

export function Evaluation() {
  const { t } = useTranslation()
  const [result, setResult] = useState<EvalResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function evaluationLabel(value: string): string {
    const key = evaluationLabelKey(value)
    return key ? t(key) : value
  }

  function translatedFailureSummary(value: EvalResult): string {
    const summary = failureSummary(value)
    return t(summary.key, summary.values)
  }

  async function runEval() {
    setLoading(true)
    setError(null)
    try {
      setResult(await api.runEval(20))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page-stack">
      <header className="page-header inline-header">
        <div>
          <span>{t('evaluation.eyebrow')}</span>
          <h1>{t('evaluation.title')}</h1>
        </div>
        <button className="primary-button" type="button" onClick={() => void runEval()} disabled={loading}>
          {loading ? t('common.running') : t('evaluation.run')}
        </button>
      </header>
      {error ? <ErrorState message={error} /> : null}
      {result ? (
        <>
          <div className="metric-grid">
            <MetricCard label={t('evaluation.totalTests')} value={result.total_tests} />
            <MetricCard
              label={t('evaluation.passRate')}
              value={formatRate(result.pass_rate)}
              detail={translatedFailureSummary(result)}
            />
            <MetricCard label={t('evaluation.toolSuccess')} value={formatRate(result.tool_call_success_rate)} />
            <MetricCard label={t('evaluation.retrievalHit')} value={formatRate(result.retrieval_hit_rate)} />
            <MetricCard label={t('evaluation.formatSuccess')} value={formatRate(result.structured_output_success_rate)} />
            <MetricCard label={t('evaluation.keywordCoverage')} value={formatRate(result.preference_compliance_rate)} />
            <MetricCard label={t('evaluation.validatorPass')} value={formatRate(result.validator_pass_rate)} />
            <MetricCard label={t('evaluation.failedCases')} value={result.failed_cases.length} />
          </div>

          <div className="evaluation-grid">
            {Object.entries(result.group_metrics).map(([groupName, metrics]) => {
              const groupEntries = Object.entries(metrics as Record<string, EvalGroupMetric>)
              return (
                <section className="content-panel evaluation-panel" key={groupName}>
                  <h2>{evaluationLabel(groupName)}</h2>
                  <div className="evaluation-table">
                    {groupEntries.map(([key, value]) => (
                      <div className="evaluation-row" key={key}>
                        <span>{evaluationLabel(key)}</span>
                        <strong>{formatRate(value.pass_rate)}</strong>
                        <small>{value.total} {t('common.cases')}</small>
                      </div>
                    ))}
                  </div>
                </section>
              )
            })}
          </div>

          <section className="content-panel">
            <h2>{t('evaluation.failedCases')}</h2>
            {result.failed_cases.length === 0 ? (
              <div className="state-box">{t('evaluation.noFailures')}</div>
            ) : (
              <div className="failed-case-list">
                {result.failed_cases.map((item) => (
                  <article className="failed-case" key={item.question}>
                    <div className="failed-case-header">
                      <strong>{item.question}</strong>
                      <span>{item.expected_tool ? evaluationLabel(item.expected_tool) : t('evaluation.noTool')}</span>
                    </div>
                    <ul>
                      {item.failure_reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                    <div className="check-grid">
                      {item.checks.map((check) => (
                        <div className={check.passed ? 'check-chip passed' : 'check-chip failed'} key={check.name}>
                          <span>{evaluationLabel(check.name)}</span>
                          <strong>{check.passed ? t('evaluation.pass') : t('evaluation.fail')}</strong>
                        </div>
                      ))}
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      ) : null}
    </div>
  )
}
