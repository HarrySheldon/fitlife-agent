import { requestV1 } from './api'
import type {
  ConfirmedSmartEntry,
  SmartEntryCreate,
  SmartEntryDraft,
  SmartEntryMutationPayload,
  EntryCapabilities, EntryAnswer, EntryUpdates, EntrySelection, ConfirmedEntryItems,
} from '../types/smartEntry'


export const smartEntryApi = {
  capabilities(): Promise<EntryCapabilities> {
    return requestV1('/smart-entry-drafts/capabilities')
  },
  startInteraction(id: string, version: number, key: string): Promise<SmartEntryDraft> {
    return interactionPost(id, 'interaction/start', key, { expected_version: version })
  },
  answerInteraction(id: string, version: number, key: string, groupId: string, answers: EntryAnswer[]): Promise<SmartEntryDraft> {
    return interactionPost(id, 'interaction/answers', key, {
      expected_version: version, question_group_id: groupId,
      answers: answers.map(({ item_id, field, value }) => ({ item_id, field, value })),
    })
  },
  correctInteraction(id: string, version: number, key: string, itemId: string, revision: number, updates: EntryUpdates): Promise<SmartEntryDraft> {
    const allowed = ['name', 'selected_catalog_id', 'amount', 'unit', 'intake_ratio', 'calories', 'carbs', 'protein', 'fat', 'basis_type']
    return interactionPost(id, 'interaction/corrections', key, {
      expected_version: version, item_id: itemId, item_revision: revision,
      updates: Object.fromEntries(Object.entries(updates).filter(([field]) => allowed.includes(field))),
    })
  },
  confirmItems(id: string, version: number, key: string, selections: EntrySelection[], estimates: EntrySelection[]): Promise<ConfirmedEntryItems> {
    const select = ({ item_id, item_revision }: EntrySelection) => ({ item_id, item_revision })
    return interactionPost(id, 'confirm-items', key, {
      expected_version: version, selections: selections.map(select), accepted_estimates: estimates.map(select),
    })
  },
  createDraft(input: SmartEntryCreate): Promise<SmartEntryDraft> {
    return requestV1('/smart-entry-drafts', {
      method: 'POST',
      body: JSON.stringify(input),
    })
  },

  findLatestDraft(logDate: string): Promise<SmartEntryDraft | null> {
    const params = new URLSearchParams({ date: logDate })
    return requestV1(`/smart-entry-drafts?${params.toString()}`)
  },

  getDraft(draftId: string): Promise<SmartEntryDraft> {
    return requestV1(`/smart-entry-drafts/${encodeURIComponent(draftId)}`)
  },

  updateDraft(
    draftId: string,
    version: number,
    payload: SmartEntryMutationPayload,
  ): Promise<SmartEntryDraft> {
    return requestV1(`/smart-entry-drafts/${encodeURIComponent(draftId)}`, {
      method: 'PATCH',
      headers: { 'If-Match': String(version) },
      body: JSON.stringify({
        log_date: payload.log_date, raw_text: payload.raw_text,
        parser_version: payload.parser_version, candidates: payload.candidates,
      }),
    })
  },

  deleteDraft(draftId: string): Promise<{ deleted: boolean }> {
    return requestV1(`/smart-entry-drafts/${encodeURIComponent(draftId)}`, {
      method: 'DELETE',
    })
  },

  analyzeDraft(draftId: string, version: number): Promise<SmartEntryDraft> {
    return requestV1(
      `/smart-entry-drafts/${encodeURIComponent(draftId)}/analyze`,
      {
        method: 'POST',
        headers: { 'If-Match': String(version) },
      },
    )
  },

  confirmDraft(
    draftId: string,
    version: number,
    idempotencyKey: string,
  ): Promise<ConfirmedSmartEntry> {
    return requestV1(
      `/smart-entry-drafts/${encodeURIComponent(draftId)}/confirm`,
      {
        method: 'POST',
        headers: {
          'If-Match': String(version),
          'Idempotency-Key': idempotencyKey,
        },
      },
    )
  },
}

function interactionPost<T>(id: string, command: string, key: string, body: unknown): Promise<T> {
  return requestV1(`/smart-entry-drafts/${encodeURIComponent(id)}/${command}`, {
    method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(body),
  })
}
