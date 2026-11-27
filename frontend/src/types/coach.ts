import type { AppLanguage, CoachAction, CoachSurface } from './index'

export interface CoachConversation {
  conversation_id: string
  title: string | null
  created_at: string
  updated_at: string
}
export interface CoachMessage {
  message_id: string
  turn_id: string
  role: 'user' | 'coach'
  metadata?: {
    model?: string
    sources?: Array<{ source?: string; heading?: string }>
    context?: { action?: string; date?: string; plan_id?: string; report_week?: string }
    // Read-only handoff from a business task: kind and id only.
    business_task_ref?: { kind: string; task_id: string }
  }
  body: string
  created_at: string
}
export interface CoachTurn {
  turn_id: string
  conversation_id: string
  status: 'queued' | 'running' | 'awaiting_user' | 'succeeded' | 'failed' | 'cancelled' | 'timed_out' | 'interrupted' | 'expired'
  stopping: boolean
  error_code: string | null
  receipt: { model?: string; context?: Omit<CoachSend, 'question'>; trace?: Record<string, unknown>; sources?: Array<{ source: string; heading?: string }> } | null
}
export interface CoachSend {
  question: string
  action: CoachAction | 'chat'
  surface: CoachSurface
  date?: string
  language?: AppLanguage
  plan_id?: string
  report_week?: string
  answer_mode?: 'brief' | 'detailed'
  read_domains?: Array<'profile' | 'training' | 'diet'>
}
export interface CoachStreamProgressEvent {
  turn_id: string
  step?: string | null
  stage: string
  status: 'started' | 'succeeded' | 'failed'
  tool_name?: string | null
  decision_count?: number
  elapsed_ms?: number
}
export type CoachStreamEvent =
  | { id: number; event: 'turn_status'; data: { turn_id: string; status: CoachTurn['status']; stopping: boolean; version: number; stage: string } }
  | { id: number; event: 'step_progress'; data: CoachStreamProgressEvent }
  | { id: number; event: 'answer_delta'; data: { turn_id: string; message_id: string; delta: string; index: number } }
  | { id: number; event: 'turn_done'; data: { turn: CoachTurn; message: CoachMessage | null } }
  | { id: number; event: 'turn_error'; data: { turn_id: string; status: string; error_code: string | null; message: string } }
export const holdsCoachSlot = (turn: CoachTurn | null) => turn?.status === 'queued' || turn?.status === 'running'
