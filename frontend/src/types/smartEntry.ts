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
}

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
  draft: SmartEntryDraft
  idempotencyKey: string
  fingerprint: string
}
