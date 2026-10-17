export type SmartCandidateKind = 'food' | 'strength' | 'cardio' | 'unknown'
export type SmartMealContext = 'breakfast' | 'lunch' | 'dinner' | 'snack' | 'other'

export interface SmartCatalogChoice {
  id: string
  name: string
  source: string
  aliases: string[]
}

export interface SmartCandidate {
  id: string
  kind: SmartCandidateKind
  raw_text: string
  normalized_text: string
  subject_text: string
  meal_context: SmartMealContext | null
  selected: boolean
  selected_catalog_id: string | null
  catalog_choices: SmartCatalogChoice[]
  issues: string[]
  values: Record<string, unknown>
  provenance: Record<string, unknown>
  assumptions: string[]
  agent_estimate_accepted: boolean
}

export interface SmartEntryDraftPayload {
  log_date: string
  raw_text: string
  parser_version: string
  candidates: SmartCandidate[]
  interaction?: EntryInteraction
}

export type EntryField = 'name' | 'selected_catalog_id' | 'amount' | 'unit' | 'intake_ratio' | 'calories' | 'carbs' | 'protein' | 'fat' | 'basis_type'
export type EntryValue = string | number | null
export type EntryUpdates = Partial<Record<EntryField, EntryValue>>
export type EntrySource = 'user_provided' | 'catalog' | 'estimated' | 'unknown' | 'measured'
export interface EntryItem {
  item_id: string
  revision: number
  state: 'needs_clarification' | 'ready' | 'saved' | 'discarded'
  values: Record<string, unknown>
  sources: Record<string, EntrySource>
  missing_fields: string[]
  assumptions: string[]
}
export interface EntryQuestion {
  item_id: string
  field: EntryField
  portion_options: string[]
}
export interface EntryQuestionGroup {
  group_id: string
  asked_at: string
  expected_version: number
  questions: EntryQuestion[]
  answered: boolean
}
export interface EntryInteraction {
  schema_version: number
  active: boolean
  clarification_rounds: number
  status: string
  items: EntryItem[]
  question_groups: EntryQuestionGroup[]
}
export interface EntrySelection { item_id: string; item_revision: number }
export interface EntryAnswer { item_id: string; field: EntryField; value: EntryValue }
export interface EntryItemCommit extends EntrySelection {
  meal_id: string
  meal_item_id: string
  record_state: 'unchanged' | 'changed' | 'deleted'
}
export interface EntryCapabilities {
  interactive_entry_enabled: boolean
  entry_task_ttl_days: number
}
export interface ConfirmedEntryItems {
  draft_id: string
  commits: EntryItemCommit[]
  remaining_draft_version: number
  replayed: boolean
}
export type SmartEntryMutationPayload = Pick<SmartEntryDraftPayload, 'log_date' | 'raw_text' | 'parser_version' | 'candidates'>

export interface SmartEntryDraft {
  id: string
  user_id: string
  payload: SmartEntryDraftPayload
  version: number
  agent_status: 'not_requested' | 'running' | 'completed' | 'failed'
  agent_prompt_version: string | null
  agent_model: string | null
  agent_metadata: Record<string, unknown>
  expires_at: string
  created_at: string
  updated_at: string
  item_commits?: EntryItemCommit[]
  dependency_validity?: { item_id: string; catalog_id: string; valid: boolean }[]
}

export interface SmartEntryCreate {
  log_date: string
  raw_text: string
}

export interface ConfirmedSmartEntry {
  draft_id: string
  log_date: string
  meal_ids: string[]
  training_session_id: string | null
  replayed: boolean
}

export interface PendingSmartEntryConfirmation {
  taskId: string
  idempotencyKey: string
  fingerprint: string
}
