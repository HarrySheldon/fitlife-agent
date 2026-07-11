import { useState } from 'react'

import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { CoachPanel } from '../components/CoachPanel'
import { PlanCard } from '../components/PlanCard'
import { api } from '../services/api'
import type { GeneratedPlan } from '../types'

export function Plan() {
  const [plan, setPlan] = useState<GeneratedPlan | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function generate() {
    setLoading(true)
    setError(null)
    try {
      setPlan(await api.generatePlan())
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
          <span>Next-week execution</span>
          <h1>Plan</h1>
        </div>
        <button className="primary-button" type="button" onClick={() => void generate()}>{loading ? 'Generating...' : 'Generate plan'}</button>
      </header>
      {error ? <ErrorState message={error} /> : null}
      <div className="plan-layout">
        <div>{plan ? <PlanCard plan={plan} /> : <EmptyState label="No plan generated yet" />}</div>
        <CoachPanel surface="plan" actions={[{ action: 'adjust_next_plan', label: 'Adjust next plan' }]} />
      </div>
    </div>
  )
}
