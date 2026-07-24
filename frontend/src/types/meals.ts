export type FoodBasisType = 'per_100g' | 'per_100ml' | 'per_serving'
export type FoodSource = 'public' | 'user_custom' | 'agent_estimate' | 'legacy_import'
export type MealType = 'breakfast' | 'lunch' | 'dinner' | 'snack' | 'custom'

export interface CustomFoodValues {
  name: string
  basis_type: FoodBasisType
  basis_amount: number
  unit: string
  calories: number
  carbs: number
  protein: number
  fat: number
}

export interface CustomFoodInput extends CustomFoodValues {
  aliases: string[]
}

export interface FoodCatalogItem extends CustomFoodValues {
  id: string
  owner_user_id: string | null
  source: FoodSource
  source_name: string
  source_record_id: string
  dataset_version: string | null
  license: string | null
  attribution: string | null
  provenance: Record<string, unknown>
  content_hash: string | null
  active: boolean
  aliases: string[]
  is_favorite: boolean
  use_count: number
  last_used_at: string | null
  rank_group: number
}

export interface MealDraftItemInput {
  amount: number
  unit: string
  catalog_food_id?: string
  custom_food?: CustomFoodValues
}

export interface MealItemSnapshot {
  catalog_food_id: string | null
  food_name: string
  amount: number
  unit: string
  basis_type: FoodBasisType
  calories: number
  carbs: number
  protein: number
  fat: number
  source: FoodSource
  is_estimate: boolean
  uncertainty: Record<string, unknown>
  assumptions: string[]
  provenance: Record<string, unknown>
  custom_food: CustomFoodValues | null
}

export interface MealDraftCreate {
  log_date: string
  name: string
  meal_type: MealType
  entry_method: 'form'
  items: MealDraftItemInput[]
}

export interface MealDraftPayload {
  log_date: string
  name: string
  meal_type: MealType
  entry_method: 'form'
  items: MealItemSnapshot[]
}

export interface MealDraft {
  id: string
  user_id: string
  payload: MealDraftPayload
  version: number
  expires_at: string
  created_at: string
  updated_at: string
}

export interface ConfirmedMeal {
  id: string
  user_id: string
  log_date: string
  name: string
  meal_type: MealType
  position: number
  entry_method: string
  items: MealItemSnapshot[]
  created_at: string
  updated_at: string
  replayed: boolean
}
