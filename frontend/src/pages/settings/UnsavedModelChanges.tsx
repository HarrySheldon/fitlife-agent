import { useContext, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { UNSAFE_DataRouterContext, useBlocker, useNavigate } from 'react-router-dom'

import { ConfirmModal } from '../../components/ConfirmModal'

function DataRouterGuard({ dirty }: { dirty: boolean }) {
  const { t } = useTranslation()
  const blocker = useBlocker(dirty)
  const blocked = blocker.state === 'blocked'
  return (
    <ConfirmModal
      open={blocked}
      title={t('settingsModel.flow.confirmDiscardTitle')}
      message={t('settingsModel.flow.confirmDiscardBody')}
      confirmLabel={t('settingsModel.flow.confirmLeave')}
      cancelLabel={t('settingsModel.flow.confirmStay')}
      tone="danger"
      onConfirm={() => { if (blocker.state === 'blocked') blocker.proceed() }}
      onCancel={() => { if (blocker.state === 'blocked') blocker.reset() }}
    />
  )
}

function LinkClickGuard({ dirty }: { dirty: boolean }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [pendingHref, setPendingHref] = useState<string | null>(null)
  const allowing = useRef(false)

  useEffect(() => {
    if (!dirty) {
      setPendingHref(null)
      return
    }
    const click = (event: MouseEvent) => {
      if (allowing.current) return
      const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>('a[href]') : null
      if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
      const href = link.getAttribute('href')
      if (!href || href.startsWith('#')) return
      event.preventDefault()
      event.stopPropagation()
      setPendingHref(href)
    }
    document.addEventListener('click', click, true)
    return () => { document.removeEventListener('click', click, true) }
  }, [dirty])

  return (
    <ConfirmModal
      open={pendingHref !== null}
      title={t('settingsModel.flow.confirmDiscardTitle')}
      message={t('settingsModel.flow.confirmDiscardBody')}
      confirmLabel={t('settingsModel.flow.confirmLeave')}
      cancelLabel={t('settingsModel.flow.confirmStay')}
      tone="danger"
      onConfirm={() => {
        const destination = pendingHref
        setPendingHref(null)
        if (!destination) return
        allowing.current = true
        navigate(destination)
        allowing.current = false
      }}
      onCancel={() => setPendingHref(null)}
    />
  )
}

export function UnsavedModelChanges({ dirty }: { dirty: boolean }) {
  const dataRouter = useContext(UNSAFE_DataRouterContext)
  useEffect(() => {
    if (!dirty) return
    const unload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', unload)
    return () => { window.removeEventListener('beforeunload', unload) }
  }, [dirty])
  return dataRouter ? <DataRouterGuard dirty={dirty} /> : <LinkClickGuard dirty={dirty} />
}
