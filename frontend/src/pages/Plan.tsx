import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { api } from '../services/api'
import type { StoredPlan } from '../types'

export function Plan() {
  const { t } = useTranslation()
  const [plans, setPlans] = useState<StoredPlan[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    api.listPlans().then((items) => { if (active) setPlans(items) })
      .catch((err) => { if (active) setError((err as Error).message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  return <div className="page-stack">
    <header className="page-header inline-header">
      <div><span>{t('plan.eyebrow')}</span><h1>{t('plan.title')}</h1></div>
      <Link className="primary-button" to="/plan/new">{t('plan.create')}</Link>
    </header>
    <section className="content-panel">
      <h2>{t('plan.history')}</h2>
      {error ? <ErrorState message={error} /> : null}
      {loading ? <LoadingState label={t('plan.loadingHistory')} /> : null}
      {!loading && !error && plans.length === 0 ? <EmptyState label={t('plan.noHistory')} /> : null}
      {plans.length > 0 ? <ul>{plans.map((item) => <li key={item.plan_id}>
        <Link to={`/plan/${item.plan_id}`}>{item.plan_id} · {new Date(item.activated_at).toLocaleString()}</Link>
      </li>)}</ul> : null}
    </section>
  </div>
}
