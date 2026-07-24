import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import { ApiRequestError } from '../services/api'
import { mealApi } from '../services/mealApi'
import type {
  ConfirmedMeal,
  FoodCatalogItem,
  MealDraft,
  MealDraftCreate,
  MealItemSnapshot,
} from '../types/meals'
import { MealEntry } from './MealEntry'


vi.mock('../services/mealApi', () => ({
  mealApi: {
    searchFoods: vi.fn(),
    setFavorite: vi.fn(),
    createCustomFood: vi.fn(),
    createDraft: vi.fn(),
    getDraft: vi.fn(),
    updateDraft: vi.fn(),
    deleteDraft: vi.fn(),
    confirmDraft: vi.fn(),
  },
}))

const rice: FoodCatalogItem = {
  id: 'food-rice',
  owner_user_id: null,
  source: 'public',
  source_name: 'USDA FoodData Central',
  source_record_id: '169756',
  dataset_version: '2026-07-24',
  name: 'White rice',
  basis_type: 'per_100g',
  basis_amount: 100,
  unit: 'g',
  calories: 365,
  carbs: 79.95,
  protein: 7.13,
  fat: 0.66,
  license: 'CC0-1.0',
  attribution: 'USDA FoodData Central',
  provenance: {},
  content_hash: 'hash',
  active: true,
  aliases: ['rice'],
  is_favorite: false,
  use_count: 0,
  last_used_at: null,
  rank_group: 3,
}

const oats: FoodCatalogItem = {
  ...rice,
  id: 'food-oats',
  source_record_id: 'oats-1',
  name: 'Rolled oats',
  calories: 379,
  carbs: 67.7,
  protein: 13.2,
  fat: 6.5,
}

function snapshots(input: MealDraftCreate): MealItemSnapshot[] {
  return input.items.map((item) => {
    const food = item.catalog_food_id === rice.id ? rice : oats
    const custom = item.custom_food
    const definition = custom ?? food
    const factor = item.amount / definition.basis_amount
    return {
      catalog_food_id: item.catalog_food_id ?? null,
      food_name: definition.name,
      amount: item.amount,
      unit: item.unit,
      basis_type: definition.basis_type,
      calories: Number((definition.calories * factor).toFixed(1)),
      carbs: Number((definition.carbs * factor).toFixed(1)),
      protein: Number((definition.protein * factor).toFixed(1)),
      fat: Number((definition.fat * factor).toFixed(1)),
      source: custom ? 'user_custom' : 'public',
      is_estimate: false,
      uncertainty: {},
      assumptions: [],
      provenance: {},
      custom_food: custom ?? null,
    }
  })
}

function draftFrom(input: MealDraftCreate, version = 1): MealDraft {
  return {
    id: 'draft-1',
    user_id: 'user-1',
    payload: { ...input, items: snapshots(input) },
    version,
    expires_at: '2026-08-23T00:00:00Z',
    created_at: '2026-07-24T00:00:00Z',
    updated_at: '2026-07-24T00:00:00Z',
  }
}

function confirmedFrom(draft: MealDraft): ConfirmedMeal {
  return {
    id: 'meal-1',
    user_id: draft.user_id,
    log_date: draft.payload.log_date,
    name: draft.payload.name,
    meal_type: draft.payload.meal_type,
    position: 1,
    entry_method: 'form',
    items: draft.payload.items,
    created_at: draft.created_at,
    updated_at: draft.updated_at,
    replayed: false,
  }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/today/meal/new?date=2026-07-24']}>
      <Routes>
        <Route path="/today/meal/new" element={<MealEntry />} />
        <Route path="/" element={<h1>Today destination</h1>} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(async () => {
  vi.clearAllMocks()
  await i18n.changeLanguage('en-US')
  vi.mocked(mealApi.searchFoods).mockResolvedValue([rice, oats])
  vi.mocked(mealApi.createDraft).mockImplementation(async (input) => draftFrom(input))
  vi.mocked(mealApi.updateDraft).mockImplementation(
    async (_id, version, input) => draftFrom(input, version + 1),
  )
  vi.mocked(mealApi.confirmDraft).mockImplementation(async () => {
    const calls = vi.mocked(mealApi.createDraft).mock.calls
    return confirmedFrom(draftFrom(calls[calls.length - 1]?.[0] ?? {
      log_date: '2026-07-24',
      name: 'Lunch',
      meal_type: 'lunch',
      entry_method: 'form',
      items: [],
    }))
  })
})

describe('MealEntry', () => {
  it('shows catalog nutrition and requires an explicit positive amount', async () => {
    renderPage()

    fireEvent.change(screen.getByLabelText('Search foods'), {
      target: { value: 'rice & oats' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('White rice')).toBeInTheDocument()
    expect(screen.getByText('365 kcal')).toBeInTheDocument()
    expect(screen.getByText('79.95 g carbs')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'Add food' })[0])

    const amount = screen.getByLabelText('Amount for White rice')
    expect(amount).toHaveValue(null)
    expect(screen.getByRole('button', { name: 'Confirm meal' })).toBeDisabled()
    fireEvent.change(amount, { target: { value: '150' } })
    expect(screen.getByRole('button', { name: 'Confirm meal' })).toBeEnabled()
  })

  it('confirms a two-food draft and redirects only after success', async () => {
    renderPage()

    fireEvent.change(screen.getByLabelText('Search foods'), {
      target: { value: 'staples' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    await screen.findByText('White rice')
    const addButtons = screen.getAllByRole('button', { name: 'Add food' })
    fireEvent.click(addButtons[0])
    fireEvent.click(addButtons[1])
    fireEvent.change(screen.getByLabelText('Amount for White rice'), {
      target: { value: '150' },
    })
    fireEvent.change(screen.getByLabelText('Amount for Rolled oats'), {
      target: { value: '80' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Confirm meal' }))

    await waitFor(() => expect(mealApi.createDraft).toHaveBeenCalledWith(
      expect.objectContaining({ items: expect.arrayContaining([
        expect.objectContaining({ catalog_food_id: rice.id, amount: 150 }),
        expect.objectContaining({ catalog_food_id: oats.id, amount: 80 }),
      ]) }),
    ))
    expect(await screen.findByRole('heading', { name: 'Today destination' })).toBeInTheDocument()
  })

  it('opens complete custom-food fields after no results and preserves values on conflict', async () => {
    vi.mocked(mealApi.searchFoods).mockResolvedValue([])
    vi.mocked(mealApi.updateDraft).mockRejectedValue(
      new ApiRequestError(
        'Draft changed in another session.',
        'DRAFT_VERSION_CONFLICT',
        'deterministic',
        409,
      ),
    )
    renderPage()

    fireEvent.change(screen.getByLabelText('Search foods'), {
      target: { value: 'family tofu' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByRole('heading', { name: 'Create custom food' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Food name'), { target: { value: 'Family tofu' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add custom food' }))
    expect(screen.queryByLabelText('Amount for Family tofu')).not.toBeInTheDocument()

    for (const [label, value] of [
      ['Calories', '120'],
      ['Carbohydrate', '4'],
      ['Protein', '12'],
      ['Fat', '6'],
    ]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } })
    }
    fireEvent.click(screen.getByRole('button', { name: 'Add custom food' }))
    fireEvent.change(screen.getByLabelText('Amount for Family tofu'), {
      target: { value: '200' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save draft' }))
    await waitFor(() => expect(mealApi.createDraft).toHaveBeenCalledOnce())
    fireEvent.change(screen.getByLabelText('Amount for Family tofu'), {
      target: { value: '210' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm meal' }))

    expect(await screen.findByText('Draft changed in another session.')).toBeInTheDocument()
    expect(screen.getByLabelText('Amount for Family tofu')).toHaveValue(210)
    expect(screen.getByRole('button', { name: 'Retry with my changes' })).toBeInTheDocument()
  })
})
