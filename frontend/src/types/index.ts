export type ProcessingMode = 'deterministic' | 'agent'

export interface ApiError {
  code: string
  message: string
}

export interface ApiResponse<T> {
  success: boolean
  data: T | null
  message: string
  processing_mode?: ProcessingMode
  error?: ApiError
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
  experience_level: 'beginner' | 'novice' | 'experienced'
  training_preference: 'strength' | 'cardio' | 'mixed'
  target_mode: 'suggested' | 'manual'
}

export type EnergyParameter = 'male' | 'female' | 'neutral'
export type ActivityLevel = 'sedentary' | 'light' | 'moderate' | 'high'
export type OverallGoal = 'fat_loss' | 'maintenance' | 'muscle_gain'
export type SafetyCondition =
  | 'pregnancy'
  | 'breastfeeding'
  | 'eating_disorder_history'
  | 'medical_condition_affecting_nutrition'
export type DailyTargetSource = 'deterministic_calculation' | 'manual' | 'agent_confirmed'
export type TargetWarning = 'TARGET_BASELINE_DEVIATION' | 'TARGET_MACRO_ENERGY_MISMATCH'

export interface ProfileVersion {
  id: string
  user_id: string
  age: number
  height_cm: number
  weight_kg: number
  energy_parameter: EnergyParameter
  activity_level: ActivityLevel
  auto_target_disabled: boolean
  safety_conditions: SafetyCondition[]
  effective_from: string
  created_at: string
}

export interface ProfileVersionUpdate {
  age: number
  height_cm: number
  weight_kg: number
  energy_parameter: EnergyParameter
  activity_level: ActivityLevel
  auto_target_disabled: boolean
  safety_conditions: SafetyCondition[]
  effective_from: string
}

export interface OverallGoalVersion {
  id: string
  user_id: string
  goal: OverallGoal
  effective_from: string
  created_at: string
}

export interface OverallGoalVersionUpdate {
  goal: OverallGoal
  effective_from: string
}

export interface DailyTargetValues {
  calories: number
  carbs: number
  protein: number
  fat: number
}

export interface DailyTargetVersion extends DailyTargetValues {
  id: string
  user_id: string
  profile_version_id: string | null
  overall_goal_version_id: string | null
  source: DailyTargetSource
  formula_version: string | null
  rationale: Record<string, unknown>
  effective_from: string
  created_at: string
}

export interface TargetPreview {
  profile_version_id: string
  overall_goal_version_id: string
  targets: DailyTargetValues
  source: Extract<DailyTargetSource, 'deterministic_calculation' | 'manual'>
  formula_version: string | null
  warnings: TargetWarning[]
  requires_confirmation: boolean
  preview_token: string
}

export interface ProfileSetup {
  profile: ProfileVersion | null
  goal: OverallGoalVersion | null
  target: DailyTargetVersion | null
  setup_complete: boolean
}

export interface ProfileSetupMutation {
  profile: ProfileVersion | null
  goal: OverallGoalVersion | null
  recalculation_preview: TargetPreview | null
  recalculation_restriction: string | null
}

export interface ConfirmTargetsInput {
  preview: TargetPreview
  effective_from: string
  acknowledge_warnings: boolean
  idempotencyKey: string
}

export interface AuthenticatedUser {
  user_id: string
  username: string | null
  email: string | null
  phone: string | null
  display_name: string
}

export interface AuthSession {
  access_token: string
  token_type: 'bearer'
  user: AuthenticatedUser
}

export interface AuthRequest {
  identifier?: string
  username?: string
  email?: string
  phone?: string
  password: string
  display_name?: string
}

export interface AccountPasswordChangeRequest {
  current_password: string
  new_password: string
}

export interface AccountDataExport {
  blob: Blob
  filename: string
}

export interface TrainingPersonalizationUpdate {
  experience_level: UserProfile['experience_level']
  training_preference: UserProfile['training_preference']
}

export interface AccountDeleteRequest {
  password: string
  confirmation: 'DELETE'
}

export type AppLanguage = 'en-US' | 'zh-CN'
export type UnitSystem = 'metric' | 'imperial'

export interface UserPreferences {
  language: AppLanguage
  unit_system: UnitSystem
  timezone: string
}

export type UserPreferencesUpdate = Partial<UserPreferences>

export type ModelProvider = 'openai' | 'custom'
export type ModelProtocol = 'responses' | 'chat_completions'
export type ModelTestStatus = 'untested' | 'success' | 'failed'
export type ModelConnectionState = 'unconfigured' | 'disabled' | 'untested' | 'success' | 'failed'

export interface ModelConnectionSettings {
  provider: ModelProvider
  protocol: ModelProtocol
  base_url: string | null
  model: string
  enabled: boolean
  api_key_configured: boolean
  api_key_hint: string | null
  test_status: ModelTestStatus
  test_error_code: string | null
  tested_at: string | null
  updated_at: string | null
  state: ModelConnectionState
}

export interface ModelSettingsUpdate {
  provider: ModelProvider
  protocol: ModelProtocol
  base_url: string | null
  model: string
  enabled: boolean
  api_key?: string
}

export interface ModelConnectionTestResult {
  status: 'success'
  protocol: ModelProtocol
  model: string
  latency_ms: number
  tested_at: string
}

export interface MealRecord {
  date: string
  meal: string
  food: string
  amount: string
  calories: number
  protein: number
  carbs: number
  fat: number
}

export interface WorkoutRecord {
  date: string
  type: string
  exercise: string
  muscle_group: string
  sets: number
  reps: number
  weight: number
  duration_min: number
}

export interface DailySummary {
  date: string
  calories: number
  protein: number
  carbs: number
  fat: number
  meal_count: number
  training_sessions: number
  training_duration_min: number
  has_data: boolean
}

export interface DailyDetail {
  summary: DailySummary
  meals: MealRecord[]
  workouts: WorkoutRecord[]
}

export interface TargetProgress {
  label: string
  current: number
  target: number
  unit: string
  remaining: number
  status: 'under' | 'met' | 'over'
}

export interface TodayOverview {
  date: string
  summary: DailySummary
  meals: MealRecord[]
  workouts: WorkoutRecord[]
  targets: TargetProgress[]
  coach_actions: CoachAction[]
}

export type CoachSurface = 'today' | 'logbook' | 'review' | 'plan' | 'profile'
export type CoachAction =
  | 'explain_today'
  | 'suggest_next_meal'
  | 'adjust_today_training'
  | 'explain_weekly_report'
  | 'adjust_next_plan'
  | 'suggest_targets'

export interface CoachActionRequest {
  surface: CoachSurface
  action: CoachAction
  date?: string
  question?: string
}

export interface CoachActionResponse {
  surface: CoachSurface
  action: CoachAction
  answer_markdown: string
  intent: string
  trace: Record<string, unknown>
  sources: Array<{ source: string; heading?: string; text?: string }>
  model: string
  request_id: string
}

export interface AgentEntryResponse {
  parsed_actions: string[]
  day: DailyDetail
}

export interface DashboardSummary {
  summary_date: string
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
  model: string
  request_id: string
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
  group_metrics: EvalGroupMetrics
  failed_cases: EvalCaseResult[]
  cases: EvalCaseResult[]
}

export interface EvalGroupMetric {
  total: number
  pass_rate: number
}

export interface EvalGroupMetrics {
  by_expected_tool: Record<string, EvalGroupMetric>
  by_retrieval_requirement: Record<string, EvalGroupMetric>
}

export interface EvalCheck {
  name: string
  passed: boolean
  expected: unknown
  observed: unknown
  reason: string
}

export interface EvalCaseResult {
  question: string
  expected_tool: string | null
  expected_retrieval_doc: string | null
  passed: boolean
  tool_ok: boolean
  retrieval_ok: boolean
  structured_ok: boolean
  keywords_ok: boolean
  validator_ok: boolean
  checks: EvalCheck[]
  failure_reasons: string[]
  trace: Record<string, unknown>
}
