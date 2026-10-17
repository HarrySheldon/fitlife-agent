import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import type { EntryItem, EntryItemCommit, EntryUpdates, EntryField, SmartCandidate } from '../../types/smartEntry'
import { numericFields } from './ClarificationPanel'

const fields: EntryField[] = ['name', 'selected_catalog_id', 'amount', 'unit', 'intake_ratio', 'calories', 'carbs', 'protein', 'fat', 'basis_type']
export function EntryItemCard({ item, candidate, commit, selected, accepted, busy, enabled, dependencyValid, logDate, onSelect, onAccept, onCorrect }: {
  item: EntryItem; candidate?: SmartCandidate; commit?: EntryItemCommit; selected: boolean; accepted: boolean
  busy: boolean; enabled: boolean; dependencyValid: boolean; logDate: string
  onSelect: (selected: boolean) => void; onAccept: (accepted: boolean) => void
  onCorrect: (updates: EntryUpdates) => Promise<unknown>
}) {
  const { t } = useTranslation()
  const fieldId = useId()
  const [updates, setUpdates] = useState<EntryUpdates>({})
  const saved = item.state === 'saved' || !!commit
  const readonly = saved || item.state === 'discarded' || !enabled
  const estimated = Object.values(item.sources).includes('estimated')
  const name = String(item.values.name ?? candidate?.subject_text ?? item.item_id)
  function update(field: EntryField, value: string) {
    onSelect(false); onAccept(false)
    setUpdates((current) => ({ ...current, [field]: value === '' ? null : numericFields.has(field) ? Number(value) : value }))
  }
  async function correct() {
    try { await onCorrect(updates); setUpdates({}) } catch { /* Retain local corrections for review and retry. */ }
  }
  return <article className="smart-candidate-row smart-item-card" aria-label={name}>
    <header className="smart-candidate-heading">
      <strong>{name}</strong><span className={`smart-item-state smart-item-state-${item.state}`}>{t(`smartInteraction.states.${item.state}`)}</span>
      {!saved ? <label className="smart-candidate-select"><input type="checkbox" checked={selected}
        disabled={busy || readonly || item.state !== 'ready' || !dependencyValid || Object.keys(updates).length > 0}
        onChange={(event) => onSelect(event.target.checked)} />{t('smartInteraction.select', { name })}</label> : null}
    </header>
    {saved ? <div className="smart-saved-note">
      <p>{t(`smartInteraction.records.${commit?.record_state ?? 'unchanged'}`)}</p>
      <Link to={`/logbook/${encodeURIComponent(logDate)}`}>{t('smartInteraction.editFormal')}</Link>
    </div> : null}
    {!dependencyValid ? <p role="alert" className="form-error">{t('smartInteraction.catalogChanged')}</p> : null}
    <p className="smart-item-explanation">{t('smartInteraction.portionExplanation')}</p>
    <fieldset disabled={readonly || busy} className="smart-item-fields">
      <legend>{t('smartInteraction.corrections')}</legend>
      <div className="smart-candidate-fields">{fields.map((field) => {
        const value = Object.prototype.hasOwnProperty.call(updates, field) ? updates[field] : field === 'selected_catalog_id' ? candidate?.selected_catalog_id : item.values[field]
        const source = Object.prototype.hasOwnProperty.call(updates, field) ? 'user_provided' : item.sources[field] ?? 'unknown'
        const choices = field === 'selected_catalog_id' ? candidate?.catalog_choices : undefined
        return <label className="smart-field" key={field}>
          <span id={`${fieldId}-${field}-label`}>{t(`smartInteraction.fields.${field}`)}</span>
          {choices?.length ? <select aria-labelledby={`${fieldId}-${field}-label`} aria-describedby={`${fieldId}-${field}-source`} value={String(value ?? '')} onChange={(event) => update(field, event.target.value)}>
            <option value="">{t('smartEntry.chooseCatalog')}</option>{choices.map((choice) => <option value={choice.id} key={choice.id}>{choice.name} · {choice.source}</option>)}
          </select> : field === 'basis_type' ? <select aria-labelledby={`${fieldId}-${field}-label`} aria-describedby={`${fieldId}-${field}-source`} value={String(value ?? '')} onChange={(event) => update(field, event.target.value)}>
            <option value="">{t('smartInteraction.unknown')}</option>{['per_100g', 'per_100ml', 'per_serving'].map((basis) => <option key={basis} value={basis}>{t(`smartInteraction.bases.${basis}`)}</option>)}
          </select> : <input aria-labelledby={`${fieldId}-${field}-label`} aria-describedby={`${fieldId}-${field}-source`} type={numericFields.has(field) ? 'number' : 'text'} step="any" value={String(value ?? '')}
            onChange={(event) => update(field, event.target.value)} />}
          <small id={`${fieldId}-${field}-source`} className="smart-field-source">{t(`smartInteraction.sources.${source}`)}</small>
        </label>
      })}</div>
      <p>{t('smartInteraction.consumedTotals')}</p>
      <button type="button" className="secondary-button" disabled={!Object.keys(updates).length} onClick={() => void correct()}>{t('smartInteraction.applyCorrection')}</button>
    </fieldset>
    {item.assumptions.length ? <div className="smart-candidate-assumptions"><strong>{t('smartEntry.assumptions')}</strong><ul>{item.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul></div> : null}
    {item.missing_fields.length ? <p className="smart-item-missing">{t('smartInteraction.missing')}: {item.missing_fields.map((field) => t(`smartInteraction.fields.${field}`)).join(', ')}</p> : null}
    {estimated ? <label className="smart-estimate-acceptance"><input type="checkbox" checked={accepted} disabled={readonly || busy || Object.keys(updates).length > 0}
      onChange={(event) => onAccept(event.target.checked)} />{t('smartInteraction.acceptEstimate')}</label> : null}
  </article>
}
