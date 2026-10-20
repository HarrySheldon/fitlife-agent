import { requestV1 } from './api'
import type { CoachConversation, CoachMessage, CoachSend, CoachTurn } from '../types/coach'

const id = encodeURIComponent
export const coachApi = {
  list: () => requestV1<{ conversations: CoachConversation[] }>('/coach/conversations'),
  create: (title?: string) => requestV1<CoachConversation>('/coach/conversations', { method: 'POST', body: JSON.stringify({ title }) }),
  rename: (conversation: string, title: string) => requestV1<CoachConversation>(`/coach/conversations/${id(conversation)}`, { method: 'PATCH', body: JSON.stringify({ title }) }),
  remove: (conversation: string) => requestV1<{ deleted: boolean }>(`/coach/conversations/${id(conversation)}`, { method: 'DELETE' }),
  messages: (conversation: string) => requestV1<{ messages: CoachMessage[] }>(`/coach/conversations/${id(conversation)}/messages`),
  active: () => requestV1<{ turn: CoachTurn | null }>('/coach/active-turn'),
  turn: (turn: string) => requestV1<CoachTurn>(`/coach/turns/${id(turn)}`),
  send: (conversation: string, payload: CoachSend, key: string) => requestV1<CoachTurn>(`/coach/conversations/${id(conversation)}/turns`, {
    method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(payload),
  }),
  cancel: (turn: string) => requestV1<CoachTurn & { notice: string }>(`/coach/turns/${id(turn)}/cancel`, { method: 'POST' }),
}
