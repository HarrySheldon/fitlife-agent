import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import { ErrorState } from '../../components/ErrorState'
import { PlanCard } from '../../components/PlanCard'
import { api } from '../../services/api'
import type { PlanDraft } from '../../types'

export function NewPlan() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const requestGenerationRef = useRef(0)
  const [draft, setDraft] = useState<PlanDraft | null>(null)
  const [generating, setGenerating] = useState(false)
  const [activating, setActivating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function generate() {
    const requestGeneration = ++requestGenerationRef.current
    setGenerating(true); setError(null); setDraft(null)
    try {
      const next = await api.createPlanDraft()
      if (requestGenerationRef.current === requestGeneration) setDraft(next)
    } catch (err) {
      if (requestGenerationRef.current === requestGeneration) setError((err as Error).message)
    } finally {
      if (requestGenerationRef.current === requestGeneration) setGenerating(false)
    }
  }

  async function activate() {
    if (!draft?.plan.validation.passed) return
    const requestGeneration = ++requestGenerationRef.current
    setGenerating(false); setActivating(true); setError(null)
    try {
      const stored = await api.activatePlan(draft.draft_id)
      if (requestGenerationRef.current === requestGeneration) navigate(`/plan/${stored.plan_id}`)
    } catch (err) {
      if (requestGenerationRef.current === requestGeneration) setError((err as Error).message)
    } finally {
      if (requestGenerationRef.current === requestGeneration) setActivating(false)
    }
  }

  return <div className="page-stack">
    <Link className="text-link" to="/plan">← {t('plan.back')}</Link>
    <header className="page-header inline-header">
      <div><span>{t('plan.eyebrow')}</span><h1>{t('plan.newTitle')}</h1></div>
      <button className="primary-button" type="button" onClick={() => void generate()} disabled={generating || activating}>
        {generating ? t('common.generating') : t('plan.generate')}
      </button>
    </header>
    {error ? <ErrorState message={error} /> : null}
    {draft ? <><PlanCard plan={draft.plan} /><button className="primary-button" type="button" onClick={() => void activate()} disabled={!draft.plan.validation.passed || activating}>
      {activating ? t('plan.activating') : t('plan.confirm')}
    </button></> : null}
  </div>
}
