import { useState } from 'react'

import { ErrorState } from '../components/ErrorState'
import { MetricCard } from '../components/MetricCard'
import { api } from '../services/api'
import type { EvalGroupMetric, EvalResult } from '../types'
import { formatGroupKey, formatRate, summarizeFailures } from './evaluationViewModel'

export function Evaluation() {
  const [result, setResult] = useState<EvalResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
          <span>Regression harness</span>
          <h1>Agent evaluation</h1>
        </div>
        <button className="primary-button" type="button" onClick={() => void runEval()} disabled={loading}>
          {loading ? 'Running...' : 'Run eval'}
        </button>
      </header>
      {error ? <ErrorState message={error} /> : null}
      {result ? (
        <>
          <div className="metric-grid">
            <MetricCard label="Total tests" value={result.total_tests} />
            <MetricCard label="Pass rate" value={formatRate(result.pass_rate)} detail={summarizeFailures(result)} />
            <MetricCard label="Tool success" value={formatRate(result.tool_call_success_rate)} />
            <MetricCard label="Retrieval hit" value={formatRate(result.retrieval_hit_rate)} />
            <MetricCard label="Format success" value={formatRate(result.structured_output_success_rate)} />
            <MetricCard label="Keyword coverage" value={formatRate(result.preference_compliance_rate)} />
            <MetricCard label="Validator pass" value={formatRate(result.validator_pass_rate)} />
            <MetricCard label="Failed cases" value={result.failed_cases.length} />
          </div>

          <div className="evaluation-grid">
            {Object.entries(result.group_metrics).map(([groupName, metrics]) => {
              const groupEntries = Object.entries(metrics as Record<string, EvalGroupMetric>)
              return (
                <section className="content-panel evaluation-panel" key={groupName}>
                  <h2>{formatGroupKey(groupName)}</h2>
                  <div className="evaluation-table">
                    {groupEntries.map(([key, value]) => (
                      <div className="evaluation-row" key={key}>
                        <span>{formatGroupKey(key)}</span>
                        <strong>{formatRate(value.pass_rate)}</strong>
                        <small>{value.total} cases</small>
                      </div>
                    ))}
                  </div>
                </section>
              )
            })}
          </div>

          <section className="content-panel">
            <h2>Failed cases</h2>
            {result.failed_cases.length === 0 ? (
              <div className="state-box">No failed cases in the latest evaluation run.</div>
            ) : (
              <div className="failed-case-list">
                {result.failed_cases.map((item) => (
                  <article className="failed-case" key={item.question}>
                    <div className="failed-case-header">
                      <strong>{item.question}</strong>
                      <span>{item.expected_tool ?? 'No tool expected'}</span>
                    </div>
                    <ul>
                      {item.failure_reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                    <div className="check-grid">
                      {item.checks.map((check) => (
                        <div className={check.passed ? 'check-chip passed' : 'check-chip failed'} key={check.name}>
                          <span>{formatGroupKey(check.name)}</span>
                          <strong>{check.passed ? 'Pass' : 'Fail'}</strong>
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
