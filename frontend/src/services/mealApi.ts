import { requestV1 } from './api'
import type {
  ConfirmedMeal,
  CustomFoodInput,
  FoodCatalogItem,
  MealDraft,
  MealDraftCreate,
} from '../types/meals'


export const mealApi = {
  searchFoods(query: string, limit = 20): Promise<FoodCatalogItem[]> {
    const params = new URLSearchParams({
      q: query,
      limit: String(limit),
    })
    return requestV1(`/catalog/foods/search?${params.toString()}`)
  },

  createCustomFood(input: CustomFoodInput): Promise<FoodCatalogItem> {
    return requestV1('/catalog/foods/custom', {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },

  setFavorite(foodId: string, favorite: boolean): Promise<{ favorite: boolean }> {
    return requestV1(`/catalog/foods/${encodeURIComponent(foodId)}/favorite`, {
      method: favorite ? 'PUT' : 'DELETE',
    })
  },

  createDraft(input: MealDraftCreate): Promise<MealDraft> {
    return requestV1('/meal-drafts', {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },

  getDraft(draftId: string): Promise<MealDraft> {
    return requestV1(`/meal-drafts/${encodeURIComponent(draftId)}`)
  },

  updateDraft(
    draftId: string,
    version: number,
    input: MealDraftCreate,
  ): Promise<MealDraft> {
    return requestV1(`/meal-drafts/${encodeURIComponent(draftId)}`, {
      method: 'PATCH',
      headers: { 'If-Match': String(version) },
      body: JSON.stringify(input),
    })
  },

  deleteDraft(draftId: string): Promise<{ deleted: boolean }> {
    return requestV1(`/meal-drafts/${encodeURIComponent(draftId)}`, {
      method: 'DELETE',
    })
  },

  confirmDraft(
    draftId: string,
    version: number,
    idempotencyKey: string,
  ): Promise<ConfirmedMeal> {
    return requestV1(`/meal-drafts/${encodeURIComponent(draftId)}/confirm`, {
      method: 'POST',
      headers: {
        'If-Match': String(version),
        'Idempotency-Key': idempotencyKey,
      },
    })
  },
}
