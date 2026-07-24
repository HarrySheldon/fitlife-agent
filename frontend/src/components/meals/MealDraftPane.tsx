import { AlertTriangle, Check, RefreshCw, Trash2, Utensils } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import {
  displayNumber,
  type NutritionTotals,
  type SelectedFood,
} from '../../domain/mealEntry'
import type { MealDraftStatus } from '../../hooks/useMealDraft'


interface MealDraftPaneProps {
  selected: SelectedFood[]
  totals: NutritionTotals
  status: MealDraftStatus
  error: string | null
  canSubmit: boolean
  canRetryConflict: boolean
  onAmountChange: (key: string, amount: string) => void
  onRemove: (key: string) => void
  onSave: () => void
  onConfirm: () => void
  onRetryConflict: () => void
}

export function MealDraftPane({
  selected,
  totals,
  status,
  error,
  canSubmit,
  canRetryConflict,
  onAmountChange,
  onRemove,
  onSave,
  onConfirm,
  onRetryConflict,
}: MealDraftPaneProps) {
  const { t } = useTranslation()
  const busy = status === 'saving' || status === 'confirming'
  return (
    <aside className="meal-draft-pane" aria-labelledby="meal-draft-title">
      <header>
        <div>
          <span>{t('mealEntry.draftEyebrow')}</span>
          <h2 id="meal-draft-title">{t('mealEntry.thisMeal')}</h2>
        </div>
        <strong>{selected.length}</strong>
      </header>

      <div className="selected-foods">
        {selected.length === 0 ? (
          <div className="draft-empty">
            <Utensils size={23} />
            <strong>{t('mealEntry.emptyDraft')}</strong>
            <span>{t('mealEntry.emptyDraftAction')}</span>
          </div>
        ) : selected.map((item) => (
          <div className="selected-food" key={item.key}>
            <div>
              <strong>{item.food.name}</strong>
              <span>{t('mealEntry.basisValue', {
                amount: item.food.basis_amount,
                unit: item.food.unit,
              })}</span>
            </div>
            <label>
              <span>{t('mealEntry.amount')}</span>
              <div>
                <input
                  aria-label={t('mealEntry.amountFor', { food: item.food.name })}
                  type="number"
                  min="0.1"
                  step="0.1"
                  value={item.amount}
                  onChange={(event) => onAmountChange(item.key, event.target.value)}
                />
                <span>{item.food.unit}</span>
              </div>
            </label>
            <button
              type="button"
              className="icon-button destructive"
              aria-label={t('mealEntry.removeFood', { food: item.food.name })}
              title={t('mealEntry.remove')}
              onClick={() => onRemove(item.key)}
            >
              <Trash2 size={17} />
            </button>
          </div>
        ))}
      </div>

      <section className="meal-totals" aria-label={t('mealEntry.totalNutrition')}>
        <NutritionTotal label={t('mealEntry.calories')} value={totals.calories} unit="kcal" />
        <NutritionTotal label={t('mealEntry.carbohydrate')} value={totals.carbs} unit="g" />
        <NutritionTotal label={t('mealEntry.protein')} value={totals.protein} unit="g" />
        <NutritionTotal label={t('mealEntry.fat')} value={totals.fat} unit="g" />
      </section>

      {error ? (
        <div className={`draft-feedback ${status === 'conflict' ? 'conflict' : ''}`}>
          <AlertTriangle size={18} />
          <div>
            <strong>{status === 'conflict'
              ? t('mealEntry.conflictTitle')
              : t('mealEntry.saveFailed')}</strong>
            <span>{error}</span>
          </div>
        </div>
      ) : null}
      {status === 'conflict' && canRetryConflict ? (
        <button type="button" className="secondary-button" onClick={onRetryConflict}>
          <RefreshCw size={17} />
          {t('mealEntry.retryChanges')}
        </button>
      ) : null}

      <footer className="meal-draft-actions">
        <button
          type="button"
          className="secondary-button"
          disabled={!canSubmit || busy}
          onClick={onSave}
        >
          {status === 'saving' ? t('common.saving') : t('mealEntry.saveDraft')}
        </button>
        <button
          type="button"
          className="primary-button"
          disabled={!canSubmit || busy}
          onClick={onConfirm}
        >
          <Check size={18} />
          {status === 'confirming' ? t('mealEntry.confirming') : t('mealEntry.confirm')}
        </button>
      </footer>
    </aside>
  )
}

function NutritionTotal({
  label,
  value,
  unit,
}: {
  label: string
  value: number
  unit: string
}) {
  return (
    <div>
      <span>{label}</span>
      <strong>{displayNumber(value)}</strong>
      <small>{unit}</small>
    </div>
  )
}
