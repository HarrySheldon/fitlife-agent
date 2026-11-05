import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

/** Native top-layer modality; business dialogs never implement their own focus lifecycle. */
export function Modal({ label, onClose, children }: { label: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)
  const close = useRef(onClose)
  close.current = onClose
  useEffect(() => {
    const dialog = ref.current!
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const overflow = document.body.style.overflow
    dialog.showModal()
    document.body.style.overflow = 'hidden'
    dialog.querySelector<HTMLElement>('button:not(:disabled), input:not(:disabled):not([type="hidden"]), textarea:not(:disabled), select:not(:disabled), summary')?.focus()
    return () => {
      if (dialog.open) dialog.close()
      document.body.style.overflow = overflow
      if (previous?.isConnected) previous.focus()
    }
  }, [])
  return createPortal(<dialog ref={ref} className="task-modal" aria-modal="true" aria-label={label} tabIndex={-1}
    onCancel={event => { event.preventDefault(); event.stopPropagation(); close.current() }}
    onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close.current(); return }
      if (event.key !== 'Tab') return
      const items = [...event.currentTarget.querySelectorAll<HTMLElement>('button, input:not([type="hidden"]), textarea, select, a[href], summary, [tabindex]')]
        .filter(item => item.tabIndex >= 0 && !item.matches(':disabled') && !item.closest('[hidden], [inert]'))
      const first = items[0], last = items[items.length - 1]
      if (!first) { event.preventDefault(); event.currentTarget.focus() }
      else if (event.shiftKey && (document.activeElement === first || !items.includes(document.activeElement as HTMLElement))) {
        event.preventDefault(); last.focus()
      } else if (!event.shiftKey && (document.activeElement === last || !items.includes(document.activeElement as HTMLElement))) {
        event.preventDefault(); first.focus()
      }
    }}>{children}</dialog>, document.body)
}
