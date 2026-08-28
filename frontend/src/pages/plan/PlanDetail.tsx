import { Bot } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { ErrorState } from '../../components/ErrorState'
import { CoachDrawer } from '../../components/CoachDrawer'
import { LoadingState } from '../../components/LoadingState'
import { PlanCard } from '../../components/PlanCard'
import { api } from '../../services/api'
import type { PlanDraft, StoredPlan } from '../../types'

export function PlanDetail() {
  const { t } = useTranslation()
  const { planId = '' } = useParams()
  const navigate = useNavigate()
  const validId = /^plan-[a-f0-9]{8,64}$/.test(planId)
  const routeRef = useRef(planId)
  const requestGenerationRef = useRef(0)
  if (routeRef.current !== planId) { routeRef.current = planId; requestGenerationRef.current += 1 }
  const [stored, setStored] = useState<StoredPlan | null>(null)
  const [draft, setDraft] = useState<PlanDraft | null>(null)
  const [instructions, setInstructions] = useState('')
  const [loading, setLoading] = useState(validId)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [coachOpen, setCoachOpen] = useState(false)
  const coachTriggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const generation = ++requestGenerationRef.current
    setDraft(null); setInstructions(''); setWorking(false)
    if (!validId) { setStored(null); setLoading(false); setError(t('plan.invalidId')); return }
    setStored(null); setLoading(true); setError(null)
    api.getPlan(planId).then((plan) => { if (requestGenerationRef.current === generation) setStored(plan) })
      .catch((err) => { if (requestGenerationRef.current === generation) setError((err as Error).message) })
      .finally(() => { if (requestGenerationRef.current === generation) setLoading(false) })
    return () => { if (requestGenerationRef.current === generation) requestGenerationRef.current += 1 }
  }, [planId, t, validId])

  async function adjust() {
    if (!stored || !instructions.trim()) return
    const generation = ++requestGenerationRef.current
    setWorking(true); setDraft(null); setError(null)
    try {
      const next = await api.createPlanAdjustmentDraft(planId, instructions.trim())
      if (requestGenerationRef.current === generation) setDraft(next)
    } catch (err) {
      if (requestGenerationRef.current === generation) setError((err as Error).message)
    } finally {
      if (requestGenerationRef.current === generation) setWorking(false)
    }
  }

  async function activate() {
    if (!draft?.plan.validation.passed) return
    const generation = ++requestGenerationRef.current
    setWorking(true); setError(null)
    try {
      const next = await api.activatePlan(draft.draft_id)
      if (requestGenerationRef.current === generation) navigate(`/plan/${next.plan_id}`)
    } catch (err) {
      if (requestGenerationRef.current === generation) setError((err as Error).message)
    } finally {
      if (requestGenerationRef.current === generation) setWorking(false)
    }
  }

  async function interpret() {
    if (!stored) throw new Error('PLAN_REQUIRED')
    return api.interpretPlan(planId)
  }

  return <div className="page-stack">
    <Link className="text-link" to="/plan">← {t('plan.back')}</Link>
    <header className="page-header"><span>{t('plan.detailEyebrow')}</span><h1>{planId}</h1></header>
    {error ? <ErrorState message={error} /> : null}
    {loading ? <LoadingState label={t('plan.loadingPlan')} /> : null}
    {stored ? <PlanCard plan={stored.plan} /> : null}
    {stored ? <button ref={coachTriggerRef} className="secondary-button coach-trigger" type="button" onClick={() => setCoachOpen(true)}><Bot size={17} />{t('coach.open')}</button> : null}
    {stored ? <section className="content-panel">
      <label htmlFor="plan-adjustment">{t('plan.instructions')}</label>
      <textarea id="plan-adjustment" value={instructions} placeholder={t('plan.instructionsPlaceholder')} onChange={(event) => setInstructions(event.target.value)} />
      <button type="button" onClick={() => void adjust()} disabled={working || !instructions.trim()}>{working ? t('common.generating') : t('plan.generateAdjustment')}</button>
    </section> : null}
    {draft ? <section className="page-stack"><h2>{t('plan.adjustmentDraft')}</h2><PlanCard plan={draft.plan} />
      <button className="primary-button" type="button" onClick={() => void activate()} disabled={working || !draft.plan.validation.passed}>{t('plan.confirmAdjustment')}</button>
    </section> : null}
    <CoachDrawer open={coachOpen} onClose={() => setCoachOpen(false)} returnFocusRef={coachTriggerRef} surface="plan" requestAction={interpret} actionsDisabled={!stored} actions={[{ action: 'adjust_next_plan', label: t('plan.generateAdjustment') }]} />
  </div>
}
