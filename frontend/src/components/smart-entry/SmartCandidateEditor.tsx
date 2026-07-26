import {
  Activity,
  AlertCircle,
  Dumbbell,
  Utensils,
} from 'lucide-react'
import type { TFunction } from 'i18next'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import type {
  SmartCandidate,
  SmartCandidateKind,
  SmartMealContext,
} from '../../types/smartEntry'


interface Props {
  candidate: SmartCandidate
  onChange: (candidate: SmartCandidate) => void
}

export function SmartCandidateEditor({ candidate, onChange }: Props) {
  const { t } = useTranslation()
  const source = String(
    candidate.provenance.source_name
    ?? candidate.provenance.source
    ?? candidate.values.source
    ?? t('smartEntry.sources.unresolved'),
  )

  function patchValue(key: string, value: unknown) {
    onChange(normalizeCandidate({
      ...candidate,
      values: { ...candidate.values, [key]: value },
    }))
  }

  function setKind(kind: SmartCandidateKind) {
    onChange(normalizeCandidate({
      ...candidate,
      kind,
      meal_context: kind === 'food'
        ? candidate.meal_context ?? 'other'
        : null,
    }))
  }

  function setCatalog(catalogId: string) {
    onChange({
      ...candidate,
      selected_catalog_id: catalogId || null,
      issues: catalogId
        ? candidate.issues.filter((issue) => ![
          'SMART_ENTRY_CATALOG_AMBIGUOUS',
          'SMART_ENTRY_CATALOG_UNMATCHED',
        ].includes(issue))
        : candidate.issues,
    })
  }

  function acceptEstimate(accepted: boolean) {
    onChange({
      ...candidate,
      agent_estimate_accepted: accepted,
      issues: accepted
        ? candidate.issues.filter(
          (issue) => issue !== 'SMART_ENTRY_AGENT_ESTIMATE_ACCEPTANCE_REQUIRED',
        )
        : uniqueIssues([
          ...candidate.issues,
          'SMART_ENTRY_AGENT_ESTIMATE_ACCEPTANCE_REQUIRED',
        ]),
    })
  }

  return (
    <article className="smart-candidate-row">
      <header className="smart-candidate-heading">
        <label className="smart-candidate-select">
          <input
            type="checkbox"
            checked={candidate.selected}
            onChange={(event) => onChange({
              ...candidate,
              selected: event.target.checked,
            })}
          />
          <span>{t('smartEntry.selectCandidate')}</span>
        </label>
        <span className="smart-candidate-kind">
          <KindIcon kind={candidate.kind} />
          {t(`smartEntry.kinds.${candidate.kind}`)}
        </span>
        <span className="smart-candidate-source">
          {t('smartEntry.source', { source })}
        </span>
      </header>

      <p className="smart-candidate-raw">{candidate.raw_text}</p>

      <div className="smart-candidate-fields">
        <Field label={t('smartEntry.kind')}>
          <select
            aria-label={`${t('smartEntry.kind')} ${candidate.raw_text}`}
            value={candidate.kind}
            onChange={(event) => setKind(event.target.value as SmartCandidateKind)}
          >
            {(['food', 'strength', 'cardio', 'unknown'] as const).map((kind) => (
              <option key={kind} value={kind}>
                {t(`smartEntry.kinds.${kind}`)}
              </option>
            ))}
          </select>
        </Field>

        {candidate.kind === 'food' ? (
          <Field label={t('smartEntry.meal')}>
            <select
              value={candidate.meal_context ?? 'other'}
              onChange={(event) => onChange({
                ...candidate,
                meal_context: event.target.value as SmartMealContext,
              })}
            >
              {(['breakfast', 'lunch', 'dinner', 'snack', 'other'] as const)
                .map((meal) => (
                  <option key={meal} value={meal}>
                    {t(`smartEntry.meals.${meal}`)}
                  </option>
                ))}
            </select>
          </Field>
        ) : null}

        {candidate.catalog_choices.length > 1
          || (
            candidate.catalog_choices.length > 0
            && candidate.selected_catalog_id === null
          ) ? (
            <Field label={t('smartEntry.catalogChoice')} wide>
              <select
                value={candidate.selected_catalog_id ?? ''}
                onChange={(event) => setCatalog(event.target.value)}
              >
                <option value="">{t('smartEntry.chooseCatalog')}</option>
                {candidate.catalog_choices.map((choice) => (
                  <option key={choice.id} value={choice.id}>
                    {choice.name} · {choice.source}
                  </option>
                ))}
              </select>
            </Field>
          ) : null}

        {candidate.kind === 'food' ? (
          <FoodFields
            candidate={candidate}
            onValue={patchValue}
            t={t}
          />
        ) : null}
        {candidate.kind === 'strength' ? (
          <StrengthFields
            candidate={candidate}
            onValue={patchValue}
            t={t}
          />
        ) : null}
        {candidate.kind === 'cardio' ? (
          <CardioFields
            candidate={candidate}
            onValue={patchValue}
            t={t}
          />
        ) : null}
      </div>

      {candidate.assumptions.length ? (
        <div className="smart-candidate-assumptions">
          <strong>{t('smartEntry.assumptions')}</strong>
          <ul>
            {candidate.assumptions.map((assumption) => (
              <li key={assumption}>{assumption}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {isAgentEstimate(candidate) ? (
        <label className="smart-estimate-acceptance">
          <input
            type="checkbox"
            checked={candidate.agent_estimate_accepted}
            onChange={(event) => acceptEstimate(event.target.checked)}
          />
          <span>{t('smartEntry.acceptEstimate')}</span>
        </label>
      ) : null}

      {candidate.issues.length ? (
        <div className="smart-candidate-issues" role="status">
          <AlertCircle size={16} />
          <ul>
            {candidate.issues.map((issue) => (
              <li key={issue}>
                {t(`smartEntry.issues.${issue}`, { defaultValue: issue })}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </article>
  )
}

function FoodFields({
  candidate,
  onValue,
  t,
}: CandidateFieldsProps) {
  const locked = candidate.selected_catalog_id !== null
  return (
    <>
      <TextField
        label={t('smartEntry.fields.foodName')}
        value={textValue(candidate, 'name')}
        disabled={locked}
        onChange={(value) => onValue('name', value)}
      />
      <NumberField
        label={t('smartEntry.fields.amount')}
        value={numberValue(candidate, 'amount')}
        disabled={locked}
        onChange={(value) => onValue('amount', value)}
      />
      <TextField
        label={t('smartEntry.fields.unit')}
        value={textValue(candidate, 'unit')}
        disabled={locked}
        onChange={(value) => onValue('unit', value)}
      />
      {(['calories', 'carbs', 'protein', 'fat'] as const).map((key) => (
        <NumberField
          key={key}
          label={t(`smartEntry.fields.${key}`)}
          value={numberValue(candidate, key)}
          disabled={locked}
          onChange={(value) => onValue(key, value)}
        />
      ))}
    </>
  )
}

function StrengthFields({ candidate, onValue, t }: CandidateFieldsProps) {
  const locked = candidate.selected_catalog_id !== null
  return (
    <>
      <TextField
        label={t('smartEntry.fields.exerciseName')}
        value={textValue(candidate, 'name')}
        disabled={locked}
        onChange={(value) => onValue('name', value)}
      />
      <TextField
        label={t('smartEntry.fields.primaryMuscle')}
        value={textValue(candidate, 'primary_muscle')}
        disabled={locked}
        onChange={(value) => onValue('primary_muscle', value)}
      />
      <NumberField
        label={t('smartEntry.fields.sets')}
        value={numberValue(candidate, 'set_count')}
        integer
        onChange={(value) => onValue('set_count', value)}
      />
      <NumberField
        label={t('smartEntry.fields.reps')}
        value={numberValue(candidate, 'reps')}
        integer
        onChange={(value) => onValue('reps', value)}
      />
      <NumberField
        label={t('smartEntry.fields.load')}
        value={numberValue(candidate, 'load_kg')}
        onChange={(value) => onValue('load_kg', value)}
      />
      <label className="smart-checkbox-field">
        <input
          type="checkbox"
          checked={Boolean(candidate.values.bodyweight)}
          onChange={(event) => onValue('bodyweight', event.target.checked)}
        />
        <span>{t('smartEntry.fields.bodyweight')}</span>
      </label>
    </>
  )
}

function CardioFields({ candidate, onValue, t }: CandidateFieldsProps) {
  const locked = candidate.selected_catalog_id !== null
  return (
    <>
      <TextField
        label={t('smartEntry.fields.exerciseName')}
        value={textValue(candidate, 'name')}
        disabled={locked}
        onChange={(value) => onValue('name', value)}
      />
      <TextField
        label={t('smartEntry.fields.primaryMuscle')}
        value={textValue(candidate, 'primary_muscle')}
        disabled={locked}
        onChange={(value) => onValue('primary_muscle', value)}
      />
      <NumberField
        label={t('smartEntry.fields.duration')}
        value={numberValue(candidate, 'duration_min')}
        onChange={(value) => onValue('duration_min', value)}
      />
      <NumberField
        label={t('smartEntry.fields.deviceCalories')}
        value={numberValue(candidate, 'device_calories')}
        onChange={(value) => onValue('device_calories', value)}
      />
      <NumberField
        label={t('smartEntry.fields.met')}
        value={numberValue(candidate, 'met')}
        disabled={locked}
        onChange={(value) => onValue('met', value)}
      />
    </>
  )
}

interface CandidateFieldsProps {
  candidate: SmartCandidate
  onValue: (key: string, value: unknown) => void
  t: TFunction
}

function Field({
  label,
  wide = false,
  children,
}: {
  label: string
  wide?: boolean
  children: ReactNode
}) {
  return (
    <label className={wide ? 'smart-field smart-field-wide' : 'smart-field'}>
      <span>{label}</span>
      {children}
    </label>
  )
}

function TextField({
  label,
  value,
  disabled = false,
  onChange,
}: {
  label: string
  value: string
  disabled?: boolean
  onChange: (value: string) => void
}) {
  return (
    <Field label={label}>
      <input
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </Field>
  )
}

function NumberField({
  label,
  value,
  disabled = false,
  integer = false,
  onChange,
}: {
  label: string
  value: number | ''
  disabled?: boolean
  integer?: boolean
  onChange: (value: number | null) => void
}) {
  return (
    <Field label={label}>
      <input
        type="number"
        min="0"
        step={integer ? '1' : 'any'}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(
          event.target.value === ''
            ? null
            : integer
              ? Number.parseInt(event.target.value, 10)
              : Number(event.target.value),
        )}
      />
    </Field>
  )
}

function KindIcon({ kind }: { kind: SmartCandidateKind }) {
  if (kind === 'food') return <Utensils size={15} />
  if (kind === 'strength') return <Dumbbell size={15} />
  return <Activity size={15} />
}

function normalizeCandidate(candidate: SmartCandidate): SmartCandidate {
  const values = candidate.values
  const resolved = new Set<string>()
  if (candidate.kind === 'food' && completeFood(values)) {
    resolved.add('SMART_ENTRY_FOOD_AMOUNT_REQUIRED')
    resolved.add('SMART_ENTRY_CATALOG_UNMATCHED')
    resolved.add('SMART_ENTRY_CATALOG_AMBIGUOUS')
  }
  if (candidate.kind === 'strength' && completeStrength(values)) {
    resolved.add('SMART_ENTRY_STRENGTH_VOLUME_REQUIRED')
    resolved.add('SMART_ENTRY_CATALOG_UNMATCHED')
    resolved.add('SMART_ENTRY_CATALOG_AMBIGUOUS')
  }
  if (candidate.kind === 'cardio' && completeCardio(values)) {
    resolved.add('SMART_ENTRY_CARDIO_DURATION_REQUIRED')
    resolved.add('SMART_ENTRY_CATALOG_UNMATCHED')
    resolved.add('SMART_ENTRY_CATALOG_AMBIGUOUS')
  }
  if (candidate.kind !== 'unknown') {
    resolved.add('SMART_ENTRY_KIND_UNRESOLVED')
  }
  const custom = candidate.selected_catalog_id === null
    && candidate.kind !== 'unknown'
  return {
    ...candidate,
    issues: candidate.issues.filter((issue) => !resolved.has(issue)),
    values: custom && !isAgentEstimate(candidate)
      ? {
        ...values,
        source: 'user_custom',
        is_estimate: false,
        ...(candidate.kind === 'food'
          ? { basis_type: basisFor(String(values.unit ?? 'serving')) }
          : {}),
      }
      : values,
    provenance: custom && !isAgentEstimate(candidate)
      ? { ...candidate.provenance, source: 'user_custom' }
      : candidate.provenance,
  }
}

function completeFood(values: Record<string, unknown>) {
  return text(values.name)
    && positive(values.amount)
    && text(values.unit)
    && nonnegative(values.calories)
    && nonnegative(values.carbs)
    && nonnegative(values.protein)
    && nonnegative(values.fat)
}

function completeStrength(values: Record<string, unknown>) {
  return text(values.name)
    && text(values.primary_muscle)
    && positiveInteger(values.set_count)
    && positiveInteger(values.reps)
}

function completeCardio(values: Record<string, unknown>) {
  return text(values.name)
    && text(values.primary_muscle)
    && positive(values.duration_min)
    && (nonnegative(values.device_calories) || positive(values.met))
}

function text(value: unknown): boolean {
  return typeof value === 'string' && Boolean(value.trim())
}

function positive(value: unknown): boolean {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
}

function nonnegative(value: unknown): boolean {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
}

function positiveInteger(value: unknown): boolean {
  return positive(value) && Number.isInteger(value)
}

function basisFor(unit: string) {
  if (unit === 'g') return 'per_100g'
  if (unit === 'ml') return 'per_100ml'
  return 'per_serving'
}

function textValue(candidate: SmartCandidate, key: string): string {
  const value = candidate.values[key]
  return typeof value === 'string' ? value : ''
}

function numberValue(
  candidate: SmartCandidate,
  key: string,
): number | '' {
  const value = candidate.values[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : ''
}

function isAgentEstimate(candidate: SmartCandidate) {
  return candidate.values.source === 'agent_estimate'
    || candidate.provenance.source === 'agent_estimate'
}

function uniqueIssues(issues: string[]) {
  return [...new Set(issues)]
}
