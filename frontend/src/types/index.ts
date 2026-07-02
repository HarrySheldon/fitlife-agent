export interface ApiResponse<T> {
  success: boolean
  data: T
  message: string
}

export interface UserProfile {
  height_cm: number
  weight_kg: number
  age: number
  gender: 'male' | 'female' | 'other'
  goal: 'fat_loss' | 'muscle_gain' | 'maintenance'
  weekly_training_frequency: number
  diet_preferences: string[]
  allergies_or_restrictions: string[]
  target_weight_kg: number
  daily_calorie_target: number
  daily_protein_target: number
}

export interface DashboardSummary {
  today_calories: number
  today_protein: number
  weekly_training_count: number
  weekly_training_duration_min: number
  calorie_trend: Array<{ date: string; value: number }>
  protein_trend: Array<{ date: string; value: number }>
  workout_count_trend: Array<{ week: string; value: number }>
  macro_distribution: Array<{ name: string; value: number }>
  meal_summary: string
  workout_summary: string
}

export interface ChatResponse {
  answer_markdown: string
  intent: string
  trace: {
    intent: string
    tool_calls: string[]
    retrieved_sources: string[]
    validation_passed: boolean
    warnings: string[]
  }
  sources: Array<{ source: string; heading: string; text: string }>
}

export interface WeeklyReport {
  title: string
  sections: Array<{ title: string; content: string }>
  checklist: string[]
  trace: Record<string, unknown>
}

export interface GeneratedPlan {
  diet_plan: Record<string, unknown>
  workout_plan: Record<string, unknown>
  validation: {
    passed: boolean
    warnings: string[]
    violations: string[]
    repair_suggestions: string[]
  }
  trace: Record<string, unknown>
}

export interface EvalResult {
  total_tests: number
  pass_rate: number
  tool_call_success_rate: number
  retrieval_hit_rate: number
  structured_output_success_rate: number
  preference_compliance_rate: number
  validator_pass_rate: number
  failed_cases: Array<Record<string, unknown>>
  cases: Array<Record<string, unknown>>
}
