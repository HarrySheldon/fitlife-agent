import type {
  CustomFoodValues,
  FoodBasisType,
  FoodCatalogItem,
  MealDraftCreate,
  MealType,
} from '../types/meals'


export interface SelectedFood {
  key: string
  food: FoodCatalogItem | CustomFoodValues
  catalogFoodId?: string
  amount: string
}

export interface CustomFoodForm {
  name: string
  basis_type: FoodBasisType
  basis_amount: string
  unit: string
  calories: string
  carbs: string
  protein: string
  fat: string
}

export interface NutritionTotals {
  calories: number
  carbs: number
  protein: number
  fat: number
}

export const emptyCustomFood: CustomFoodForm = {
  name: '',
  basis_type: 'per_100g',
  basis_amount: '100',
  unit: 'g',
  calories: '',
  carbs: '',
  protein: '',
  fat: '',
}

export function customFoodValues(form: CustomFoodForm): CustomFoodValues | null {
  const name = form.name.trim()
  const unit = form.unit.trim()
  const basisAmount = Number(form.basis_amount)
  const nutrition = [form.calories, form.carbs, form.protein, form.fat]
  if (
    !name
    || !unit
    || !Number.isFinite(basisAmount)
    || basisAmount <= 0
    || nutrition.some((value) => value === '' || !Number.isFinite(Number(value)) || Number(value) < 0)
  ) {
    return null
  }
  return {
    name,
    basis_type: form.basis_type,
    basis_amount: basisAmount,
    unit,
    calories: Number(form.calories),
    carbs: Number(form.carbs),
    protein: Number(form.protein),
    fat: Number(form.fat),
  }
}

export function nutritionTotals(items: SelectedFood[]): NutritionTotals {
  return items.reduce(
    (sum, item) => {
      const amount = Number(item.amount)
      if (!Number.isFinite(amount) || amount <= 0) return sum
      const factor = amount / item.food.basis_amount
      return {
        calories: sum.calories + item.food.calories * factor,
        carbs: sum.carbs + item.food.carbs * factor,
        protein: sum.protein + item.food.protein * factor,
        fat: sum.fat + item.food.fat * factor,
      }
    },
    { calories: 0, carbs: 0, protein: 0, fat: 0 },
  )
}

export function hasValidAmounts(items: SelectedFood[]): boolean {
  return items.length > 0 && items.every(
    (item) => Number.isFinite(Number(item.amount)) && Number(item.amount) > 0,
  )
}

export function mealDraftInput({
  logDate,
  mealName,
  mealType,
  selected,
}: {
  logDate: string
  mealName: string
  mealType: MealType
  selected: SelectedFood[]
}): MealDraftCreate {
  return {
    log_date: logDate,
    name: mealName.trim(),
    meal_type: mealType,
    entry_method: 'form',
    items: selected.map((item) => ({
      amount: Number(item.amount),
      unit: item.food.unit,
      ...(item.catalogFoodId
        ? { catalog_food_id: item.catalogFoodId }
        : { custom_food: item.food }),
    })),
  }
}

export function displayNumber(value: number): string {
  return String(Number(value.toFixed(2)))
}
