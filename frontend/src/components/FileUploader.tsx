import { Upload } from 'lucide-react'
import { useState } from 'react'

interface FileUploaderProps {
  label: string
  onUpload: (file: File) => Promise<void>
}

export function FileUploader({ label, onUpload }: FileUploaderProps) {
  const [status, setStatus] = useState<string>('No file selected')
  const [busy, setBusy] = useState(false)

  async function handleChange(file?: File) {
    if (!file) return
    setBusy(true)
    setStatus(`Uploading ${file.name}`)
    try {
      await onUpload(file)
      setStatus(`Uploaded ${file.name}`)
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
      <small>{busy ? 'Working...' : status}</small>
      <input type="file" accept=".csv" onChange={(event) => handleChange(event.target.files?.[0])} />
    </label>
  )
}
