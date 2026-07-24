import { Check, Plus, Search, Star, Utensils } from 'lucide-react'
import type { FormEvent } from 'react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import {
  customFoodValues,
  displayNumber,
  emptyCustomFood,
  type CustomFoodForm,
} from '../../domain/mealEntry'
import { mealApi } from '../../services/mealApi'
import type {
  CustomFoodValues,
  FoodBasisType,
  FoodCatalogItem,
} from '../../types/meals'


type CatalogFilter = 'all' | 'favorites' | 'mine'

interface FoodCatalogPaneProps {
  selectedCatalogIds: string[]
  onAddCatalogFood: (food: FoodCatalogItem) => void
  onAddCustomFood: (food: CustomFoodValues) => void
}

export function FoodCatalogPane({
  selectedCatalogIds,
  onAddCatalogFood,
  onAddCustomFood,
}: FoodCatalogPaneProps) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<FoodCatalogItem[]>([])
  const [filter, setFilter] = useState<CatalogFilter>('all')
  const [searching, setSearching] = useState(false)
  const [searched, setSearched] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showCustom, setShowCustom] = useState(false)
  const [custom, setCustom] = useState<CustomFoodForm>(emptyCustomFood)
  const [customError, setCustomError] = useState<string | null>(null)

  const visibleResults = results.filter((food) => {
    if (filter === 'favorites') return food.is_favorite
    if (filter === 'mine') return food.owner_user_id !== null
    return true
  })

  async function searchFoods(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSearching(true)
    setError(null)
    try {
      const found = await mealApi.searchFoods(query)
      setResults(found)
      setSearched(true)
      if (found.length === 0) {
        setCustom((current) => ({ ...current, name: current.name || query.trim() }))
        setShowCustom(true)
      }
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
      setSearching(false)
    }
  }

  async function toggleFavorite(food: FoodCatalogItem) {
    try {
      const next = !food.is_favorite
      await mealApi.setFavorite(food.id, next)
      setResults((current) => current.map((item) => (
        item.id === food.id ? { ...item, is_favorite: next } : item
      )))
    } catch (cause) {
      setError((cause as Error).message)
    }
  }

  function addCustomFood() {
    const values = customFoodValues(custom)
    if (!values) {
      setCustomError(t('mealEntry.completeNutrition'))
      return
    }
    onAddCustomFood(values)
    setCustomError(null)
    setCustom(emptyCustomFood)
    setShowCustom(false)
  }

  return (
    <section className="food-catalog-pane" aria-labelledby="food-catalog-title">
      <header>
        <div>
          <span>{t('mealEntry.catalogEyebrow')}</span>
          <h2 id="food-catalog-title">{t('mealEntry.catalog')}</h2>
        </div>
        <button
          type="button"
          className="secondary-button"
          onClick={() => setShowCustom((current) => !current)}
        >
          <Plus size={17} />
          {t('mealEntry.customFood')}
        </button>
      </header>

      <form className="food-search" onSubmit={(event) => void searchFoods(event)}>
        <label className="search-input">
          <Search size={18} />
          <span className="sr-only">{t('mealEntry.searchFoods')}</span>
          <input
            aria-label={t('mealEntry.searchFoods')}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('mealEntry.searchPlaceholder')}
          />
        </label>
        <button className="primary-button" type="submit" disabled={searching}>
          {searching ? t('mealEntry.searching') : t('mealEntry.search')}
        </button>
      </form>

      <div className="catalog-filter" aria-label={t('mealEntry.filter')}>
        {(['all', 'favorites', 'mine'] as const).map((value) => (
          <button
            key={value}
            type="button"
            className={filter === value ? 'active' : ''}
            onClick={() => setFilter(value)}
          >
            {t(`mealEntry.filters.${value}`)}
          </button>
        ))}
      </div>

      {error ? <p className="inline-error">{error}</p> : null}
      <div className="food-results" aria-live="polite">
        {visibleResults.map((food) => {
          const alreadyAdded = selectedCatalogIds.includes(food.id)
          return (
            <article className="food-result" key={food.id}>
              <div className="food-result-main">
                <div>
                  <strong>{food.name}</strong>
                  <span>{t('mealEntry.basisValue', {
                    amount: food.basis_amount,
                    unit: food.unit,
                  })}</span>
                </div>
                <button
                  type="button"
                  className={`icon-button ${food.is_favorite ? 'active' : ''}`}
                  aria-label={food.is_favorite
                    ? t('mealEntry.removeFavorite')
                    : t('mealEntry.addFavorite')}
                  title={food.is_favorite
                    ? t('mealEntry.removeFavorite')
                    : t('mealEntry.addFavorite')}
                  onClick={() => void toggleFavorite(food)}
                >
                  <Star size={17} fill={food.is_favorite ? 'currentColor' : 'none'} />
                </button>
              </div>
              <div className="food-nutrients">
                <strong>{displayNumber(food.calories)} kcal</strong>
                <span>{displayNumber(food.carbs)} {t('mealEntry.carbsShort')}</span>
                <span>{displayNumber(food.protein)} {t('mealEntry.proteinShort')}</span>
                <span>{displayNumber(food.fat)} {t('mealEntry.fatShort')}</span>
              </div>
              <button
                type="button"
                className="secondary-button icon-command"
                aria-label={t('mealEntry.addFood')}
                disabled={alreadyAdded}
                onClick={() => onAddCatalogFood(food)}
              >
                {alreadyAdded ? <Check size={17} /> : <Plus size={17} />}
                <span>{alreadyAdded ? t('mealEntry.added') : t('mealEntry.add')}</span>
              </button>
            </article>
          )
        })}
        {searched && visibleResults.length === 0 ? (
          <div className="catalog-empty">
            <Utensils size={22} />
            <strong>{t('mealEntry.noResults')}</strong>
            <span>{t('mealEntry.noResultsAction')}</span>
          </div>
        ) : null}
      </div>

      {showCustom ? (
        <CustomFoodEditor
          form={custom}
          error={customError}
          onChange={setCustom}
          onAdd={addCustomFood}
        />
      ) : null}
    </section>
  )
}

function CustomFoodEditor({
  form,
  error,
  onChange,
  onAdd,
}: {
  form: CustomFoodForm
  error: string | null
  onChange: (next: CustomFoodForm) => void
  onAdd: () => void
}) {
  const { t } = useTranslation()
  return (
    <section className="custom-food-editor" aria-labelledby="custom-food-title">
      <header>
        <h3 id="custom-food-title">{t('mealEntry.createCustom')}</h3>
        <span>{t('mealEntry.completeRequired')}</span>
      </header>
      <div className="custom-food-fields">
        <label className="wide">
          <span>{t('mealEntry.foodName')}</span>
          <input
            aria-label={t('mealEntry.foodName')}
            value={form.name}
            onChange={(event) => onChange({ ...form, name: event.target.value })}
          />
        </label>
        <label>
          <span>{t('mealEntry.basis')}</span>
          <select
            value={form.basis_type}
            onChange={(event) => {
              const basis = event.target.value as FoodBasisType
              onChange({
                ...form,
                basis_type: basis,
                basis_amount: basis === 'per_serving' ? '1' : '100',
                unit: basis === 'per_100ml' ? 'ml' : basis === 'per_100g' ? 'g' : t('mealEntry.servingUnit'),
              })
            }}
          >
            <option value="per_100g">{t('mealEntry.per100g')}</option>
            <option value="per_100ml">{t('mealEntry.per100ml')}</option>
            <option value="per_serving">{t('mealEntry.perServing')}</option>
          </select>
        </label>
        <label>
          <span>{t('mealEntry.basisAmount')}</span>
          <input
            type="number"
            min="0.1"
            step="0.1"
            value={form.basis_amount}
            onChange={(event) => onChange({ ...form, basis_amount: event.target.value })}
          />
        </label>
        <label>
          <span>{t('mealEntry.unit')}</span>
          <input
            value={form.unit}
            disabled={form.basis_type !== 'per_serving'}
            onChange={(event) => onChange({ ...form, unit: event.target.value })}
          />
        </label>
        {([
          ['calories', 'mealEntry.calories'],
          ['carbs', 'mealEntry.carbohydrate'],
          ['protein', 'mealEntry.protein'],
          ['fat', 'mealEntry.fat'],
        ] as const).map(([field, label]) => (
          <label key={field}>
            <span>{t(label)}</span>
            <input
              aria-label={t(label)}
              type="number"
              min="0"
              step="0.1"
              value={form[field]}
              onChange={(event) => onChange({ ...form, [field]: event.target.value })}
            />
          </label>
        ))}
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      <button type="button" className="primary-button" onClick={onAdd}>
        <Plus size={17} />
        {t('mealEntry.addCustom')}
      </button>
    </section>
  )
}
