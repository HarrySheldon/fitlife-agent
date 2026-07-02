import { ChatBox } from '../components/ChatBox'
import { ErrorState } from '../components/ErrorState'
import { useChat } from '../hooks/useChat'

export function Chat() {
  const { messages, loading, error, send } = useChat()
  return (
    <div className="page-stack">
      <header className="page-header">
        <span>FitLife Coach Agent</span>
        <h1>Ask about records, rules, reports, and plans</h1>
      </header>
      {error ? <ErrorState message={error} /> : null}
      <ChatBox messages={messages} loading={loading} onSend={send} />
    </div>
  )
}
