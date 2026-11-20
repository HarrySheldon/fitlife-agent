import { CheckCircle2, Dumbbell, Plus, Trash2 } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import {
  progressApi,
  type EquipmentId,
  type ExperienceLevel,
  type InjuryArea,
  type InjuryLimitation,
  type PreferredSplit,
} from '../services/progressApi'

const EQUIPMENT_LIST: EquipmentId[] = [
  'barbell',
  'dumbbell',
  'machine',
  'cable',
  'bodyweight',
  'kettlebell',
  'resistance_band',
  'cardio_machine',
]

const EXPERIENCE_LIST: ExperienceLevel[] = ['beginner', 'intermediate', 'advanced']
const SPLIT_LIST: PreferredSplit[] = ['auto', 'full_body', 'upper_lower', 'push_pull_legs', 'custom']
const INJURY_AREAS: InjuryArea[] = [
  'knee',
  'lower_back',
  'shoulder',
  'wrist',
  'elbow',
  'ankle',
  'hip',
  'neck',
  'other',
]

export function TrainingContextCard() {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [equipment, setEquipment] = useState<EquipmentId[]>(['bodyweight', 'dumbbell'])
  const [weeklyDays, setWeeklyDays] = useState(3)
  const [durationMin, setDurationMin] = useState(45)
  const [experience, setExperience] = useState<ExperienceLevel>('beginner')
  const [split, setSplit] = useState<PreferredSplit>('auto')
  const [injuries, setInjuries] = useState<InjuryLimitation[]>([])
  const [notes, setNotes] = useState('')
  const [newInjuryArea, setNewInjuryArea] = useState<InjuryArea>('knee')
  const [newInjuryNote, setNewInjuryNote] = useState('')
  const [feedback, setFeedback] = useState<{ kind: 'success' | 'error'; message: string } | null>(null)

  useEffect(() => {
    let active = true
    progressApi
      .getTrainingContext()
      .then((res) => {
        if (!active) return
        const ctx = res.training_context
        setEquipment(ctx.available_equipment.length ? ctx.available_equipment : ['bodyweight'])
        setWeeklyDays(ctx.weekly_available_days)
        setDurationMin(ctx.session_duration_min)
        setExperience(ctx.experience_level)
        setSplit(ctx.preferred_split)
        setInjuries(ctx.injury_or_limitations)
        setNotes(ctx.notes)
      })
      .catch(() => {
        // Keep defaults if offline or uninitialized
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  function toggleEquipment(id: EquipmentId) {
    setEquipment((current) => {
      if (current.includes(id)) {
        return current.length > 1 ? current.filter((item) => item !== id) : current
      }
      return [...current, id]
    })
  }

  function addInjury() {
    setInjuries((current) => [...current, { area: newInjuryArea, note: newInjuryNote.trim() }])
    setNewInjuryNote('')
  }

  function removeInjury(index: number) {
    setInjuries((current) => current.filter((_, idx) => idx !== index))
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setFeedback(null)
    try {
      await progressApi.updateTrainingContext({
        available_equipment: equipment,
        weekly_available_days: weeklyDays,
        session_duration_min: durationMin,
        experience_level: experience,
        preferred_split: split,
        injury_or_limitations: injuries,
        notes,
      })
      setFeedback({ kind: 'success', message: t('trainingContext.saved') })
    } catch (cause) {
      setFeedback({
        kind: 'error',
        message: cause instanceof Error ? cause.message : t('trainingContext.saveFailed'),
      })
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <section className="panel-card training-context-card">
        <p>{t('common.loadingData')}</p>
      </section>
    )
  }

  return (
    <section className="panel-card training-context-card" aria-labelledby="training-context-title">
      <header className="section-card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Dumbbell size={18} />
          <h2 id="training-context-title">{t('trainingContext.title')}</h2>
        </div>
        <p className="muted-copy">{t('trainingContext.description')}</p>
      </header>

      <form onSubmit={(e) => void handleSave(e)} className="training-context-form">
        <fieldset className="chip-fieldset">
          <legend>{t('trainingContext.equipment')}</legend>
          <div className="chip-row">
            {EQUIPMENT_LIST.map((item) => {
              const selected = equipment.includes(item)
              return (
                <button
                  key={item}
                  type="button"
                  className={`chip-toggle ${selected ? 'selected' : ''}`}
                  aria-pressed={selected}
                  onClick={() => toggleEquipment(item)}
                >
                  {t(`trainingContext.equipmentOptions.${item}`)}
                </button>
              )
            })}
          </div>
        </fieldset>

        <div className="training-context-grid">
          <label>
            <span>{t('trainingContext.weeklyDays')}</span>
            <input
              type="number"
              min={1}
              max={7}
              value={weeklyDays}
              onChange={(e) => setWeeklyDays(Math.min(7, Math.max(1, Number(e.target.value) || 1)))}
            />
          </label>
          <label>
            <span>{t('trainingContext.durationMin')}</span>
            <input
              type="number"
              min={15}
              max={180}
              step={5}
              value={durationMin}
              onChange={(e) => setDurationMin(Math.min(180, Math.max(15, Number(e.target.value) || 30)))}
            />
          </label>
          <label>
            <span>{t('trainingContext.experience')}</span>
            <select value={experience} onChange={(e) => setExperience(e.target.value as ExperienceLevel)}>
              {EXPERIENCE_LIST.map((lvl) => (
                <option key={lvl} value={lvl}>
                  {t(`trainingContext.experienceOptions.${lvl}`)}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{t('trainingContext.preferredSplit')}</span>
            <select value={split} onChange={(e) => setSplit(e.target.value as PreferredSplit)}>
              {SPLIT_LIST.map((sp) => (
                <option key={sp} value={sp}>
                  {t(`trainingContext.splitOptions.${sp}`)}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="injury-editor">
          <span>{t('trainingContext.injuries')}</span>
          {injuries.length ? (
            <ul className="injury-list">
              {injuries.map((item, idx) => (
                <li key={`${item.area}-${idx}`}>
                  <strong>{t(`trainingContext.injuryAreas.${item.area}`)}</strong>
                  {item.note ? <span> · {item.note}</span> : null}
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={t('trainingContext.removeInjury')}
                    onClick={() => removeInjury(idx)}
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted-copy">{t('trainingContext.noInjuries')}</p>
          )}
          <div className="injury-add-row">
            <select
              aria-label={t('trainingContext.injuryArea')}
              value={newInjuryArea}
              onChange={(e) => setNewInjuryArea(e.target.value as InjuryArea)}
            >
              {INJURY_AREAS.map((area) => (
                <option key={area} value={area}>
                  {t(`trainingContext.injuryAreas.${area}`)}
                </option>
              ))}
            </select>
            <input
              type="text"
              placeholder={t('trainingContext.injuryNotePlaceholder')}
              value={newInjuryNote}
              onChange={(e) => setNewInjuryNote(e.target.value)}
            />
            <button type="button" className="secondary-button" onClick={addInjury}>
              <Plus size={15} />
              {t('trainingContext.addInjury')}
            </button>
          </div>
        </div>

        <label className="training-context-notes">
          <span>{t('trainingContext.notes')}</span>
          <input
            type="text"
            maxLength={500}
            placeholder={t('trainingContext.notesPlaceholder')}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </label>

        {feedback ? (
          <div className={`settings-feedback ${feedback.kind}`} role={feedback.kind === 'error' ? 'alert' : 'status'}>
            {feedback.kind === 'success' ? <CheckCircle2 size={16} /> : null}
            {feedback.message}
          </div>
        ) : null}

        <div>
          <button type="submit" className="primary-button" disabled={saving}>
            {saving ? t('common.saving') : t('trainingContext.save')}
          </button>
        </div>
      </form>
    </section>
  )
}
