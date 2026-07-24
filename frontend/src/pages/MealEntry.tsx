import { ArrowLeft } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { FoodCatalogPane } from '../components/meals/FoodCatalogPane'
import { MealDraftPane } from '../components/meals/MealDraftPane'
import {
  hasValidAmounts,
  mealDraftInput,
  nutritionTotals,
  type SelectedFood,
} from '../domain/mealEntry'
import { useMealDraft } from '../hooks/useMealDraft'
import type {
  CustomFoodValues,
  FoodCatalogItem,
  MealDraftCreate,
  MealType,
} from '../types/meals'


export function MealEntry() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [logDate, setLogDate] = useState(() => validDate(params.get('date')) ?? browserDate())
  const [mealType, setMealType] = useState<MealType>('lunch')
  const [mealName, setMealName] = useState(() => t('mealEntry.defaultName'))
  const [selected, setSelected] = useState<SelectedFood[]>([])
  const initialDraft = useMemo<MealDraftCreate>(() => ({
    log_date: logDate,
    name: mealName,
    meal_type: mealType,
    entry_method: 'form',
    items: [],
  }), [])
  const draft = useMealDraft(initialDraft)
  const totals = nutritionTotals(selected)
  const canSubmit = hasValidAmounts(selected) && Boolean(mealName.trim())

  function addCatalogFood(food: FoodCatalogItem) {
    setSelected((current) => current.some((item) => item.catalogFoodId === food.id)
      ? current
      : [...current, {
        key: `catalog:${food.id}`,
        food,
        catalogFoodId: food.id,
        amount: '',
      }])
  }

  function addCustomFood(food: CustomFoodValues) {
    setSelected((current) => [...current, {
      key: `custom:${globalThis.crypto.randomUUID()}`,
      food,
      amount: '',
    }])
  }

  function currentInput(): MealDraftCreate {
    return mealDraftInput({
      logDate,
      mealName,
      mealType,
      selected,
    })
  }

  async function saveDraft() {
    if (!canSubmit) return
    try {
      await draft.save(currentInput())
    } catch {
      // The hook owns recoverable errors and retry state.
    }
  }

  async function confirmMeal() {
    if (!canSubmit) return
    try {
      await draft.save(currentInput())
      await draft.confirm()
      navigate('/', { replace: true })
    } catch {
      // The hook keeps local form values and exposes recovery actions.
    }
  }

  async function retryConflict() {
    try {
      await draft.resolveConflict('overwrite')
    } catch {
      // Leave the editor untouched for another explicit retry.
    }
  }

  return (
    <div className="page-stack meal-entry-page">
      <header className="meal-entry-header">
        <button
          type="button"
          className="icon-button"
          aria-label={t('mealEntry.back')}
          title={t('mealEntry.back')}
          onClick={() => navigate('/')}
        >
          <ArrowLeft size={19} />
        </button>
        <div>
          <span>{t('mealEntry.eyebrow')}</span>
          <h1>{t('mealEntry.title')}</h1>
        </div>
        <label>
          <span>{t('mealEntry.date')}</span>
          <input type="date" value={logDate} onChange={(event) => setLogDate(event.target.value)} />
        </label>
        <label className="meal-name-field">
          <span>{t('mealEntry.mealName')}</span>
          <input value={mealName} onChange={(event) => setMealName(event.target.value)} />
        </label>
        <label>
          <span>{t('mealEntry.mealType')}</span>
          <select value={mealType} onChange={(event) => setMealType(event.target.value as MealType)}>
            {(['breakfast', 'lunch', 'dinner', 'snack', 'custom'] as const).map((value) => (
              <option key={value} value={value}>{t(`mealEntry.types.${value}`)}</option>
            ))}
          </select>
        </label>
      </header>

      <div className="meal-entry-workspace">
        <FoodCatalogPane
          selectedCatalogIds={selected.flatMap((item) => (
            item.catalogFoodId ? [item.catalogFoodId] : []
          ))}
          onAddCatalogFood={addCatalogFood}
          onAddCustomFood={addCustomFood}
        />
        <MealDraftPane
          selected={selected}
          totals={totals}
          status={draft.status}
          error={draft.error}
          canSubmit={canSubmit}
          canRetryConflict={draft.draft !== null}
          onAmountChange={(key, amount) => setSelected((current) => current.map((item) => (
            item.key === key ? { ...item, amount } : item
          )))}
          onRemove={(key) => setSelected((current) => current.filter((item) => item.key !== key))}
          onSave={() => void saveDraft()}
          onConfirm={() => void confirmMeal()}
          onRetryConflict={() => void retryConflict()}
        />
      </div>
    </div>
  )
}

function validDate(value: string | null): string | null {
  return value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null
}

function browserDate(): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]))
  return `${values.year}-${values.month}-${values.day}`
}
