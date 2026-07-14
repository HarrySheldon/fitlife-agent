import { ChatBox } from '../components/ChatBox'
import { ErrorState } from '../components/ErrorState'
import { useChat } from '../hooks/useChat'
import { useTranslation } from 'react-i18next'

export function Chat() {
  const { t } = useTranslation()
  const { messages, loading, error, send } = useChat()
  return (
    <div className="page-stack">
      <header className="page-header">
        <span>{t('legacy.chatTitle')}</span>
        <h1>{t('legacy.chatEyebrow')}</h1>
      </header>
      {error ? <ErrorState message={error} /> : null}
      <ChatBox messages={messages} loading={loading} onSend={send} />
    </div>
  )
}
