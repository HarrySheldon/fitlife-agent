import { useTranslation } from 'react-i18next'

export function LoadingState({ label }: { label?: string }) {
  const { t } = useTranslation()
  return <div className="state-box">{label ?? t('common.loadingData')}...</div>
}
