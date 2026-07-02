import { useState } from 'react'

import { ErrorState } from '../components/ErrorState'
import { MetricCard } from '../components/MetricCard'
import { api } from '../services/api'
import type { EvalResult } from '../types'

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
        <button className="primary-button" type="button" onClick={() => void runEval()}>{loading ? 'Running...' : 'Run eval'}</button>
      </header>
      {error ? <ErrorState message={error} /> : null}
      {result ? (
        <>
          <div className="metric-grid">
            <MetricCard label="Total tests" value={result.total_tests} />
            <MetricCard label="Pass rate" value={`${Math.round(result.pass_rate * 100)}%`} />
            <MetricCard label="Tool success" value={`${Math.round(result.tool_call_success_rate * 100)}%`} />
            <MetricCard label="Retrieval hit" value={`${Math.round(result.retrieval_hit_rate * 100)}%`} />
          </div>
          <section className="content-panel">
            <h2>Failed cases</h2>
            <pre>{JSON.stringify(result.failed_cases, null, 2)}</pre>
          </section>
        </>
      ) : null}
    </div>
  )
}
