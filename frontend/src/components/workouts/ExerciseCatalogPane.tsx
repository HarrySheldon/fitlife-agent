import { Check, Dumbbell, HeartPulse, Plus, Search, Star } from 'lucide-react'
import type { FormEvent } from 'react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { workoutApi } from '../../services/workoutApi'
import type {
  CustomExerciseInput,
  ExerciseCatalogItem,
  ExerciseType,
} from '../../types/workouts'

type CatalogFilter = 'all' | 'favorites' | 'mine'
type ExerciseTypeFilter = 'all' | ExerciseType

interface CustomExerciseForm {
  name: string
  exerciseType: ExerciseType
  primaryMuscle: string
  secondaryMuscles: string
  met: string
  aliases: string
}

const emptyCustomExercise: CustomExerciseForm = {
  name: '',
  exerciseType: 'strength',
  primaryMuscle: '',
  secondaryMuscles: '',
  met: '',
  aliases: '',
}

interface ExerciseCatalogPaneProps {
  selectedCatalogIds: string[]
  onAddExercise: (exercise: ExerciseCatalogItem) => void
}

export function ExerciseCatalogPane({
  selectedCatalogIds,
  onAddExercise,
}: ExerciseCatalogPaneProps) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<ExerciseCatalogItem[]>([])
  const [filter, setFilter] = useState<CatalogFilter>('all')
  const [typeFilter, setTypeFilter] = useState<ExerciseTypeFilter>('all')
  const [searching, setSearching] = useState(false)
  const [searched, setSearched] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showCustom, setShowCustom] = useState(false)
  const [custom, setCustom] = useState<CustomExerciseForm>(emptyCustomExercise)
  const [customError, setCustomError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const visibleResults = results.filter((exercise) => {
    if (typeFilter !== 'all' && exercise.exercise_type !== typeFilter) return false
    if (filter === 'favorites') return exercise.is_favorite
    if (filter === 'mine') return exercise.owner_user_id !== null
    return true
  })

  async function searchExercises(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSearching(true)
    setError(null)
    try {
      const found = await workoutApi.searchExercises(query)
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

  async function toggleFavorite(exercise: ExerciseCatalogItem) {
    try {
      const next = !exercise.is_favorite
      await workoutApi.setFavorite(exercise.id, next)
      setResults((current) => current.map((item) => (
        item.id === exercise.id ? { ...item, is_favorite: next } : item
      )))
    } catch (cause) {
      setError((cause as Error).message)
    }
  }

  async function createCustomExercise() {
    const input = customExerciseInput(custom)
    if (!input) {
      setCustomError(t('workoutEntry.customCompleteError'))
      return
    }
    setCreating(true)
    setCustomError(null)
    try {
      const created = await workoutApi.createCustomExercise(input)
      setResults((current) => [created, ...current])
      onAddExercise(created)
      setCustom(emptyCustomExercise)
      setShowCustom(false)
    } catch (cause) {
      setCustomError((cause as Error).message)
    } finally {
      setCreating(false)
    }
  }

  return (
    <section className="exercise-catalog-pane" aria-labelledby="exercise-catalog-title">
      <header>
        <div>
          <span>{t('workoutEntry.catalogEyebrow')}</span>
          <h2 id="exercise-catalog-title">{t('workoutEntry.catalog')}</h2>
        </div>
        <button
          type="button"
          className="secondary-button"
          onClick={() => setShowCustom((current) => !current)}
        >
          <Plus size={17} />
          {t('workoutEntry.customExercise')}
        </button>
      </header>

      <form className="exercise-search" onSubmit={(event) => void searchExercises(event)}>
        <label className="search-input">
          <Search size={18} />
          <span className="sr-only">{t('workoutEntry.searchExercises')}</span>
          <input
            aria-label={t('workoutEntry.searchExercises')}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('workoutEntry.searchPlaceholder')}
          />
        </label>
        <button className="primary-button" type="submit" disabled={searching}>
          {searching ? t('workoutEntry.searching') : t('workoutEntry.search')}
        </button>
      </form>

      <div className="exercise-catalog-filters">
        <div className="catalog-filter" aria-label={t('workoutEntry.typeFilter')}>
          {(['all', 'strength', 'cardio'] as const).map((value) => (
            <button
              key={value}
              type="button"
              className={typeFilter === value ? 'active' : ''}
              onClick={() => setTypeFilter(value)}
            >
              {t(`workoutEntry.types.${value}`)}
            </button>
          ))}
        </div>
        <div className="catalog-filter" aria-label={t('workoutEntry.catalogFilter')}>
          {(['all', 'favorites', 'mine'] as const).map((value) => (
            <button
              key={value}
              type="button"
              className={filter === value ? 'active' : ''}
              onClick={() => setFilter(value)}
            >
              {t(`workoutEntry.filters.${value}`)}
            </button>
          ))}
        </div>
      </div>

      {error ? <p className="inline-error">{error}</p> : null}
      <div className="exercise-results" aria-live="polite">
        {visibleResults.map((exercise) => {
          const alreadyAdded = selectedCatalogIds.includes(exercise.id)
          return (
            <article className="exercise-result" key={exercise.id}>
              <div className="exercise-result-icon" aria-hidden="true">
                {exercise.exercise_type === 'strength'
                  ? <Dumbbell size={19} />
                  : <HeartPulse size={19} />}
              </div>
              <div className="exercise-result-main">
                <strong>{exercise.name}</strong>
                <span>
                  {exercise.primary_muscle}
                  {exercise.met
                    ? ` · ${t('workoutEntry.metValue', { met: exercise.met })}`
                    : ''}
                </span>
              </div>
              <button
                type="button"
                className={`icon-button ${exercise.is_favorite ? 'active' : ''}`}
                aria-label={exercise.is_favorite
                  ? t('workoutEntry.removeFavorite')
                  : t('workoutEntry.addFavorite')}
                title={exercise.is_favorite
                  ? t('workoutEntry.removeFavorite')
                  : t('workoutEntry.addFavorite')}
                onClick={() => void toggleFavorite(exercise)}
              >
                <Star size={17} fill={exercise.is_favorite ? 'currentColor' : 'none'} />
              </button>
              <button
                type="button"
                className="secondary-button icon-command"
                aria-label={t('workoutEntry.addExercise')}
                disabled={alreadyAdded}
                onClick={() => onAddExercise(exercise)}
              >
                {alreadyAdded ? <Check size={17} /> : <Plus size={17} />}
                <span>{alreadyAdded ? t('workoutEntry.added') : t('workoutEntry.add')}</span>
              </button>
            </article>
          )
        })}
        {searched && visibleResults.length === 0 ? (
          <div className="catalog-empty">
            <Dumbbell size={22} />
            <strong>{t('workoutEntry.noResults')}</strong>
            <span>{t('workoutEntry.noResultsAction')}</span>
          </div>
        ) : null}
      </div>

      {showCustom ? (
        <CustomExerciseEditor
          form={custom}
          error={customError}
          creating={creating}
          onChange={setCustom}
          onCreate={() => void createCustomExercise()}
        />
      ) : null}
    </section>
  )
}

function CustomExerciseEditor({
  form,
  error,
  creating,
  onChange,
  onCreate,
}: {
  form: CustomExerciseForm
  error: string | null
  creating: boolean
  onChange: (next: CustomExerciseForm) => void
  onCreate: () => void
}) {
  const { t } = useTranslation()
  return (
    <section className="custom-exercise-editor" aria-labelledby="custom-exercise-title">
      <header>
        <h3 id="custom-exercise-title">{t('workoutEntry.createCustom')}</h3>
        <span>{t('workoutEntry.customComplete')}</span>
      </header>
      <div className="custom-exercise-fields">
        <label className="wide">
          <span>{t('workoutEntry.exerciseName')}</span>
          <input
            aria-label={t('workoutEntry.exerciseName')}
            value={form.name}
            onChange={(event) => onChange({ ...form, name: event.target.value })}
          />
        </label>
        <label>
          <span>{t('workoutEntry.exerciseType')}</span>
          <select
            value={form.exerciseType}
            onChange={(event) => onChange({
              ...form,
              exerciseType: event.target.value as ExerciseType,
            })}
          >
            <option value="strength">{t('workoutEntry.types.strength')}</option>
            <option value="cardio">{t('workoutEntry.types.cardio')}</option>
          </select>
        </label>
        <label>
          <span>{t('workoutEntry.primaryMuscle')}</span>
          <input
            aria-label={t('workoutEntry.primaryMuscle')}
            value={form.primaryMuscle}
            onChange={(event) => onChange({ ...form, primaryMuscle: event.target.value })}
          />
        </label>
        <label className="wide">
          <span>{t('workoutEntry.secondaryMuscles')}</span>
          <input
            value={form.secondaryMuscles}
            placeholder={t('workoutEntry.commaSeparated')}
            onChange={(event) => onChange({ ...form, secondaryMuscles: event.target.value })}
          />
        </label>
        <label>
          <span>{t('workoutEntry.met')}</span>
          <input
            aria-label={t('workoutEntry.met')}
            type="number"
            min="0.1"
            step="0.1"
            value={form.met}
            onChange={(event) => onChange({ ...form, met: event.target.value })}
          />
        </label>
        <label>
          <span>{t('workoutEntry.aliases')}</span>
          <input
            value={form.aliases}
            placeholder={t('workoutEntry.commaSeparated')}
            onChange={(event) => onChange({ ...form, aliases: event.target.value })}
          />
        </label>
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      <button type="button" className="primary-button" disabled={creating} onClick={onCreate}>
        <Plus size={17} />
        {creating ? t('common.saving') : t('workoutEntry.createAndAdd')}
      </button>
    </section>
  )
}

function customExerciseInput(form: CustomExerciseForm): CustomExerciseInput | null {
  const met = form.met.trim() ? Number(form.met) : null
  if (
    !form.name.trim()
    || !form.primaryMuscle.trim()
    || (met !== null && (!Number.isFinite(met) || met <= 0))
  ) return null
  return {
    name: form.name.trim(),
    exercise_type: form.exerciseType,
    primary_muscle: form.primaryMuscle.trim(),
    secondary_muscles: splitList(form.secondaryMuscles),
    met,
    aliases: splitList(form.aliases),
  }
}

function splitList(value: string): string[] {
  return value.split(/[,，]/).map((item) => item.trim()).filter(Boolean)
}
