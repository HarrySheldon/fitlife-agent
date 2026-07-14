import { Upload } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

interface FileUploaderProps {
  label: string
  onUpload: (file: File) => Promise<void>
}

export function FileUploader({ label, onUpload }: FileUploaderProps) {
  const { t } = useTranslation()
  const [status, setStatus] = useState<string>(() => t('components.noFile'))
  const [busy, setBusy] = useState(false)

  async function handleChange(file?: File) {
    if (!file) return
    setBusy(true)
    setStatus(t('components.uploadingFile', { name: file.name }))
    try {
      await onUpload(file)
      setStatus(t('components.uploadedFile', { name: file.name }))
    } catch (err) {
      setStatus((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <label className="upload-box">
      <Upload size={20} />
      <span>{label}</span>
      <small>{busy ? t('components.working') : status}</small>
      <input type="file" accept=".csv" onChange={(event) => handleChange(event.target.files?.[0])} />
    </label>
  )
}
