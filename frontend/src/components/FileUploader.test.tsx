import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createInstance } from 'i18next'
import { I18nextProvider, initReactI18next } from 'react-i18next'
import { expect, it, vi } from 'vitest'

import { FileUploader } from './FileUploader'


it('re-translates semantic upload states while preserving dynamic values', async () => {
  const i18n = createInstance()
  await i18n.use(initReactI18next).init({
    lng: 'en-US',
    fallbackLng: 'en-US',
    interpolation: { escapeValue: false },
    resources: {
      'en-US': {
        translation: {
          components: {
            noFile: 'No file selected',
            uploadingFile: 'Uploading {{name}}',
            uploadedFile: 'Uploaded {{name}}',
          },
        },
      },
      'zh-CN': {
        translation: {
          components: {
            noFile: '尚未选择文件',
            uploadingFile: '正在上传 {{name}}',
            uploadedFile: '已上传 {{name}}',
          },
        },
      },
    },
  })

  let finishUpload!: () => void
  const serverError = '服务端原始错误'
  const onUpload = vi.fn()
    .mockImplementationOnce(() => new Promise<void>((resolve) => { finishUpload = resolve }))
    .mockRejectedValueOnce(new Error(serverError))
  const user = userEvent.setup()
  const { container } = render(
    <I18nextProvider i18n={i18n}>
      <FileUploader label="meals.csv" onUpload={onUpload} />
    </I18nextProvider>,
  )
  const input = container.querySelector<HTMLInputElement>('input[type="file"]')!

  expect(screen.getByText('No file selected')).toBeInTheDocument()
  await act(() => i18n.changeLanguage('zh-CN'))
  expect(screen.getByText('尚未选择文件')).toBeInTheDocument()

  await act(() => i18n.changeLanguage('en-US'))
  const selectedFile = new File(['date,meal'], '真实饮食.csv', { type: 'text/csv' })
  await user.upload(input, selectedFile)
  expect(screen.getByText(`Uploading ${selectedFile.name}`)).toBeInTheDocument()
  await act(() => i18n.changeLanguage('zh-CN'))
  expect(screen.getByText(`正在上传 ${selectedFile.name}`)).toBeInTheDocument()

  await act(async () => finishUpload())
  expect(screen.getByText(`已上传 ${selectedFile.name}`)).toBeInTheDocument()
  await act(() => i18n.changeLanguage('en-US'))
  expect(screen.getByText(`Uploaded ${selectedFile.name}`)).toBeInTheDocument()

  await user.upload(input, new File(['date,meal'], 'retry.csv', { type: 'text/csv' }))
  expect(await screen.findByText(serverError)).toBeInTheDocument()
  await act(() => i18n.changeLanguage('zh-CN'))
  expect(screen.getByText(serverError)).toBeInTheDocument()
})
