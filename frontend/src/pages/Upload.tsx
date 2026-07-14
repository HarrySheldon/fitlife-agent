import { FileUploader } from '../components/FileUploader'
import { api } from '../services/api'
import { useTranslation } from 'react-i18next'

export function Upload() {
  const { t } = useTranslation()
  return (
    <div className="page-stack">
      <header className="page-header">
        <span>{t('legacy.uploadEyebrow')}</span>
        <h1>{t('legacy.uploadTitle')}</h1>
      </header>
      <div className="upload-grid">
        <FileUploader label="meals.csv" onUpload={(file) => api.upload('meals', file).then(() => undefined)} />
        <FileUploader label="workouts.csv" onUpload={(file) => api.upload('workouts', file).then(() => undefined)} />
      </div>
    </div>
  )
}
