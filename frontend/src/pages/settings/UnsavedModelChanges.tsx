import { useContext, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { UNSAFE_DataRouterContext, useBlocker } from 'react-router-dom'


function DataRouterGuard({ dirty }: { dirty: boolean }) {
  const { t } = useTranslation()
  const blocker = useBlocker(dirty)
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    if (window.confirm(t('settingsModel.flow.discard'))) blocker.proceed()
    else blocker.reset()
  }, [blocker, t])
  return null
}

export function UnsavedModelChanges({ dirty }: { dirty: boolean }) {
  const dataRouter = useContext(UNSAFE_DataRouterContext)
  const { t } = useTranslation()
  useEffect(() => {
    if (!dirty) return
    const unload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    // Plain MemoryRouter embedding has no route blocker; production uses the
    // data router and its blocker for links, programmatic navigation and POP.
    const click = (event: MouseEvent) => {
      const link = event.target instanceof Element ? event.target.closest('a[href]') : null
      if (!dataRouter && link && !event.ctrlKey && !event.metaKey && !window.confirm(t('settingsModel.flow.discard'))) {
        event.preventDefault()
        event.stopPropagation()
      }
    }
    window.addEventListener('beforeunload', unload)
    document.addEventListener('click', click, true)
    return () => { window.removeEventListener('beforeunload', unload); document.removeEventListener('click', click, true) }
  }, [dirty, dataRouter, t])
  return dataRouter ? <DataRouterGuard dirty={dirty} /> : null
}
