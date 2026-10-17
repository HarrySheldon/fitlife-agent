import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { EntryAnswer, EntryInteraction, EntryQuestionGroup } from '../../types/smartEntry'

export function ClarificationPanel({ interaction, busy, disabled, onAnswer }: {
  interaction: EntryInteraction; busy: boolean; disabled: boolean
  onAnswer: (groupId: string, answers: EntryAnswer[]) => Promise<unknown>
}) {
  const { t } = useTranslation()
  const currentGroup = interaction.question_groups.find((group) => !group.answered)
  const questions = currentGroup?.questions.filter((question) => {
    const item = interaction.items.find((entry) => entry.item_id === question.item_id)
    return item?.state === 'needs_clarification' && item.missing_fields.includes(question.field)
  }) ?? []
  const pending = currentGroup && questions.length ? { ...currentGroup, questions } : null
  return <section className="smart-clarification" aria-label={t('smartInteraction.questions')}>
    <p>{t('smartInteraction.rounds', { count: interaction.clarification_rounds })}</p>
    {pending ? <QuestionGroup key={pending.group_id} group={pending} interaction={interaction} busy={busy || disabled} onAnswer={onAnswer} /> : null}
    {interaction.clarification_rounds >= 2 && !pending ? <p role="status">{t('smartInteraction.manualFallback')}</p> : null}
  </section>
}
function QuestionGroup({ group, interaction, busy, onAnswer }: {
  group: EntryQuestionGroup; interaction: EntryInteraction; busy: boolean
  onAnswer: (groupId: string, answers: EntryAnswer[]) => Promise<unknown>
}) {
  const { t } = useTranslation()
  const [values, setValues] = useState<Record<string, string>>({})
  const [unknown, setUnknown] = useState<Record<string, boolean>>({})
  async function submit() {
    const answers = group.questions.map((question) => {
      const key = `${question.item_id}:${question.field}`
      const input = values[key] ?? ''
      return { item_id: question.item_id, field: question.field,
        value: unknown[key] || !input.trim() ? null : numericFields.has(question.field) ? Number(input) : input }
    })
    try { await onAnswer(group.group_id, answers) } catch { /* Preserve answers for explicit retry. */ }
  }
  return <div>
    {group.questions.map((question) => {
      const key = `${question.item_id}:${question.field}`
      const numeric = numericFields.has(question.field)
      return <fieldset key={key} disabled={busy} className="smart-question">
        <legend>{String(interaction.items.find((item) => item.item_id === question.item_id)?.values.name ?? question.item_id)} · {t(`smartInteraction.fields.${question.field}`)}</legend>
        <label className="smart-field">
          <span>{t(`smartInteraction.fields.${question.field}`)}</span>
          <input type={numeric ? 'number' : 'text'} step="any" list={`options-${key}`}
            value={values[key] ?? ''} disabled={unknown[key]}
            onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))} />
          <datalist id={`options-${key}`}>{question.portion_options.map((option) => <option key={option} value={option} />)}</datalist>
        </label>
        <label className="smart-checkbox-field"><input type="checkbox" checked={unknown[key] ?? false}
          onChange={(event) => setUnknown((current) => ({ ...current, [key]: event.target.checked }))} />{t('smartInteraction.unknown')}</label>
      </fieldset>
    })}
    <button type="button" className="secondary-button" disabled={busy} onClick={() => void submit()}>{t('smartInteraction.answer')}</button>
  </div>
}
export const numericFields = new Set(['amount', 'intake_ratio', 'calories', 'carbs', 'protein', 'fat'])
