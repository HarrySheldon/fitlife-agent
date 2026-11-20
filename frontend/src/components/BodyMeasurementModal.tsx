import { Scale, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { progressApi, type BodyMeasurementSummary } from '../services/progressApi'

interface BodyMeasurementModalProps {
  open: boolean
  defaultDate: string
  onClose: () => void
  onSaved?: (summary: BodyMeasurementSummary) => void
}

export function BodyMeasurementModal({
  open,
  defaultDate,
  onClose,
  onSaved,
}: BodyMeasurementModalProps) {
  const { t } = useTranslation()
  const [measuredDate, setMeasuredDate] = useState(defaultDate)
  const [weightKg, setWeightKg] = useState('')
  const [bodyFatPct, setBodyFatPct] = useState('')
  const [waistCm, setWaistCm] = useState('')
  const [chestCm, setChestCm] = useState('')
  const [hipCm, setHipCm] = useState('')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!open) return null

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const payload = {
      measured_date: measuredDate || defaultDate,
      weight_kg: parseOpt(weightKg),
      body_fat_pct: parseOpt(bodyFatPct),
      waist_cm: parseOpt(waistCm),
      chest_cm: parseOpt(chestCm),
      hip_cm: parseOpt(hipCm),
      note: note.trim(),
    }
    if (
      payload.weight_kg === null &&
      payload.body_fat_pct === null &&
      payload.waist_cm === null &&
      payload.chest_cm === null &&
      payload.hip_cm === null
    ) {
      setError(t('bodyMetrics.requireAtLeastOne'))
      return
    }
    setSaving(true)
    setError(null)
    try {
      const result = await progressApi.createBodyMeasurement(payload)
      setWeightKg('')
      setBodyFatPct('')
      setWaistCm('')
      setChestCm('')
      setHipCm('')
      setNote('')
      onSaved?.(result.summary)
      onClose()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('bodyMetrics.saveFailed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="body-metric-modal-title">
      <div className="task-modal body-metric-modal">
        <header className="plan-adjustment-dialog__header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Scale size={20} />
            <h2 id="body-metric-modal-title">{t('bodyMetrics.modalTitle')}</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label={t('common.back')}>
            <X size={18} />
          </button>
        </header>

        <form onSubmit={(e) => void handleSubmit(e)} className="body-metric-form">
          <div className="body-metric-grid">
            <label>
              <span>{t('bodyMetrics.date')}</span>
              <input
                type="date"
                value={measuredDate}
                onChange={(e) => setMeasuredDate(e.target.value)}
                required
              />
            </label>
            <label>
              <span>{t('bodyMetrics.weightKg')}</span>
              <input
                type="number"
                step="0.1"
                min="25"
                max="350"
                placeholder="70.0"
                value={weightKg}
                onChange={(e) => setWeightKg(e.target.value)}
              />
            </label>
            <label>
              <span>{t('bodyMetrics.bodyFatPct')}</span>
              <input
                type="number"
                step="0.1"
                min="2"
                max="70"
                placeholder="18.0"
                value={bodyFatPct}
                onChange={(e) => setBodyFatPct(e.target.value)}
              />
            </label>
            <label>
              <span>{t('bodyMetrics.waistCm')}</span>
              <input
                type="number"
                step="0.1"
                min="30"
                max="250"
                placeholder="80.0"
                value={waistCm}
                onChange={(e) => setWaistCm(e.target.value)}
              />
            </label>
            <label>
              <span>{t('bodyMetrics.chestCm')}</span>
              <input
                type="number"
                step="0.1"
                min="40"
                max="250"
                value={chestCm}
                onChange={(e) => setChestCm(e.target.value)}
              />
            </label>
            <label>
              <span>{t('bodyMetrics.hipCm')}</span>
              <input
                type="number"
                step="0.1"
                min="40"
                max="250"
                value={hipCm}
                onChange={(e) => setHipCm(e.target.value)}
              />
            </label>
          </div>

          <label className="body-metric-note">
            <span>{t('bodyMetrics.note')}</span>
            <input
              type="text"
              maxLength={300}
              placeholder={t('bodyMetrics.notePlaceholder')}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>

          {error ? <p role="alert" className="field-error">{error}</p> : null}

          <div className="modal-actions">
            <button type="button" className="secondary-button" onClick={onClose} disabled={saving}>
              {t('common.back')}
            </button>
            <button type="submit" className="primary-button" disabled={saving}>
              {saving ? t('common.saving') : t('common.save')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function parseOpt(raw: string): number | null {
  const trimmed = raw.trim()
  if (!trimmed) return null
  const num = Number(trimmed)
  return Number.isFinite(num) ? num : null
}
