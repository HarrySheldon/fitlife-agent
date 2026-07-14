import { Upload } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

interface FileUploaderProps {
  label: string
  onUpload: (file: File) => Promise<void>
}

type UploadStatus =
  | { kind: 'idle' }
  | { kind: 'uploading'; name: string }
  | { kind: 'uploaded'; name: string }
  | { kind: 'error'; message: string }

export function FileUploader({ label, onUpload }: FileUploaderProps) {
  const { t } = useTranslation()
  const [status, setStatus] = useState<UploadStatus>({ kind: 'idle' })

  async function handleChange(file?: File) {
    if (!file) return
    setStatus({ kind: 'uploading', name: file.name })
    try {
      await onUpload(file)
      setStatus({ kind: 'uploaded', name: file.name })
    } catch (err) {
      setStatus({ kind: 'error', message: (err as Error).message })
    }
  }

  const statusText = status.kind === 'idle'
    ? t('components.noFile')
    : status.kind === 'uploading'
      ? t('components.uploadingFile', { name: status.name })
      : status.kind === 'uploaded'
        ? t('components.uploadedFile', { name: status.name })
        : status.message

  return (
    <label className="upload-box">
      <Upload size={20} />
      <span>{label}</span>
      <small>{statusText}</small>
      <input type="file" accept=".csv" onChange={(event) => handleChange(event.target.files?.[0])} />
    </label>
  )
}
