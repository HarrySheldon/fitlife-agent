import { requestV1 } from './api'
import type {
  ConfirmedSmartEntry,
  SmartEntryCreate,
  SmartEntryDraft,
  SmartEntryDraftPayload,
} from '../types/smartEntry'


export const smartEntryApi = {
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
    payload: SmartEntryDraftPayload,
  ): Promise<SmartEntryDraft> {
    return requestV1(`/smart-entry-drafts/${encodeURIComponent(draftId)}`, {
      method: 'PATCH',
      headers: { 'If-Match': String(version) },
      body: JSON.stringify(payload),
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
