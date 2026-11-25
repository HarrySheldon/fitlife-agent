export const MODEL_WORKSPACE_CHANGED_EVENT = 'fitlife:model-workspace-changed'

export interface ModelWorkspaceChangedDetail {
  configured: boolean
}

export function notifyModelWorkspaceChanged(configured: boolean): void {
  if (typeof window === 'undefined' || typeof window.dispatchEvent !== 'function') {
    return
  }
  window.dispatchEvent(
    new CustomEvent<ModelWorkspaceChangedDetail>(MODEL_WORKSPACE_CHANGED_EVENT, {
      detail: { configured },
    }),
  )
}
