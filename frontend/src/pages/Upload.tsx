import { FileUploader } from '../components/FileUploader'
import { api } from '../services/api'

export function Upload() {
  return (
    <div className="page-stack">
      <header className="page-header">
        <span>Data intake</span>
        <h1>Upload meal and workout CSV files</h1>
      </header>
      <div className="upload-grid">
        <FileUploader label="Upload meals.csv" onUpload={(file) => api.upload('meals', file).then(() => undefined)} />
        <FileUploader label="Upload workouts.csv" onUpload={(file) => api.upload('workouts', file).then(() => undefined)} />
      </div>
    </div>
  )
}
