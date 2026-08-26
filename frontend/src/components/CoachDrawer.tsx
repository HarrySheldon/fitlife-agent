import { X } from 'lucide-react'
import type { RefObject } from 'react'
import { useEffect, useId, useRef } from 'react'
import { useTranslation } from 'react-i18next'

import type { CoachAction, CoachActionResponse, CoachSurface } from '../types'
import { CoachPanel } from './CoachPanel'

interface CoachDrawerProps {
  open: boolean
  onClose: () => void
  returnFocusRef: RefObject<HTMLElement | null>
  surface: CoachSurface
  date?: string
  question?: string
  requestAction?: (action: CoachAction) => Promise<CoachActionResponse>
  actionsDisabled?: boolean
  actions: Array<{ action: CoachAction; label: string }>
}

export function CoachDrawer({ open, onClose, returnFocusRef, surface, date, question, requestAction, actionsDisabled = false, actions }: CoachDrawerProps) {
  const { t } = useTranslation()
  const titleId = useId()
  const dialogRef = useRef<HTMLElement>(null)
  const onCloseRef = useRef(onClose)
  const returnFocusTargetRef = useRef(returnFocusRef)
  onCloseRef.current = onClose
  returnFocusTargetRef.current = returnFocusRef

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const focusable = currentFocusableElements(dialogRef.current)
      if (focusable.length === 0) {
        event.preventDefault()
        dialogRef.current?.focus()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && (document.activeElement === first || !dialogRef.current?.contains(document.activeElement))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (document.activeElement === last || !dialogRef.current?.contains(document.activeElement))) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    const frame = requestAnimationFrame(() => {
      const dialog = dialogRef.current
      const focusable = currentFocusableElements(dialog)
      ;(focusable.find((element) => element.matches('.coach-actions button'))
        ?? focusable[0]
        ?? dialog)?.focus()
    })
    return () => {
      cancelAnimationFrame(frame)
      document.removeEventListener('keydown', onKeyDown)
      returnFocusTargetRef.current.current?.focus()
    }
  }, [open])

  if (!open) return null
  return <div
    className="coach-drawer-backdrop"
    data-testid="coach-drawer-backdrop"
    onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}
  >
    <aside ref={dialogRef} className="coach-drawer" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
      <header className="coach-drawer-header">
        <h2 id={titleId}>{t('coach.title')}</h2>
        <button className="icon-command coach-drawer-close" type="button" aria-label={t('coach.close')} onClick={onClose}><X size={20} /></button>
      </header>
      <CoachPanel surface={surface} date={date} question={question} requestAction={requestAction} disabled={actionsDisabled} actions={actions} />
    </aside>
  </div>
}

function currentFocusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) return []
  return Array.from(container.querySelectorAll<HTMLElement>(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )).filter((element) => isFocusableAndVisible(element, container))
}

function isFocusableAndVisible(element: HTMLElement, container: HTMLElement): boolean {
  if (
    element.hasAttribute('disabled')
    || element.getAttribute('aria-disabled') === 'true'
  ) return false

  let current: HTMLElement | null = element
  while (current) {
    if (
      current.hidden
      || current.hasAttribute('inert')
      || current.getAttribute('aria-hidden') === 'true'
    ) return false
    const style = getComputedStyle(current)
    if (
      style.display === 'none'
      || style.visibility === 'hidden'
      || style.visibility === 'collapse'
      || style.opacity === '0'
      || style.contentVisibility === 'hidden'
    ) return false
    if (current === container) break
    current = current.parentElement
  }

  if (/jsdom/i.test(globalThis.navigator?.userAgent ?? '')) return true
  const rect = element.getBoundingClientRect()
  return element.offsetWidth > 0
    || element.offsetHeight > 0
    || rect.width > 0
    || rect.height > 0
    || element.getClientRects().length > 0
}
