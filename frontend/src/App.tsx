import { useEffect, useRef, useState, type FormEvent } from 'react'
import { getSession, sendChat, type Approval, type Message } from './api'
import ToolPanel from './ToolPanel.tsx'

const SESSION_KEY = 'shophelp-session'
const POLL_MS = 3000

/** Text bubbles only: customer messages and agent replies (tool calls come in the side panel). */
function chatLines(messages: Message[]) {
  return messages.flatMap((m, i) =>
    m.role === 'user' || (m.role === 'assistant' && m.content)
      ? [{ key: i, who: m.role === 'user' ? 'you' : 'agent', text: m.content as string }]
      : [],
  )
}

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(() => sessionStorage.getItem(SESSION_KEY))
  const [messages, setMessages] = useState<Message[]>([])
  const [approval, setApproval] = useState<Approval | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  // Restore the conversation after a page reload (the server may have forgotten it).
  useEffect(() => {
    if (!sessionId) return
    getSession(sessionId)
      .then((s) => {
        setMessages(s.messages)
        setApproval(s.pending_approval)
      })
      .catch(() => newConversation())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // While a refund waits for staff, check back until it is decided.
  useEffect(() => {
    if (!approval || !sessionId) return
    const timer = setInterval(async () => {
      try {
        const s = await getSession(sessionId)
        setMessages(s.messages)
        setApproval(s.pending_approval)
      } catch {
        /* keep polling; the error banner is for user actions */
      }
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [approval, sessionId])

  useEffect(() => endRef.current?.scrollIntoView({ behavior: 'smooth' }), [messages, busy])

  function newConversation() {
    sessionStorage.removeItem(SESSION_KEY)
    setSessionId(null)
    setMessages([])
    setApproval(null)
    setError(null)
  }

  async function send(e: FormEvent) {
    e.preventDefault()
    const text = draft.trim()
    if (!text || busy || approval) return
    setDraft('')
    setError(null)
    setBusy(true)
    setMessages((m) => [...m, { role: 'user', content: text }]) // show it right away
    try {
      const res = await sendChat(text, sessionId)
      sessionStorage.setItem(SESSION_KEY, res.session_id)
      setSessionId(res.session_id)
      setMessages((m) => [...m.slice(0, -1), ...res.messages])
      setApproval(res.pending_approval)
    } catch (err) {
      setMessages((m) => m.slice(0, -1))
      setDraft(text)
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="layout">
      <div className="app">
        <header>
          <h1>ShopHelp</h1>
          <a href="#staff" className="staff-link">
            Staff view
          </a>
          <button type="button" className="secondary" onClick={newConversation} disabled={busy}>
            New conversation
          </button>
        </header>

        <main className="chat" aria-live="polite">
          {messages.length === 0 && (
            <p className="hint">Hi! I can help with your orders: cancel, return, exchange, or change an address.</p>
          )}
          {chatLines(messages).map((line) => (
            <div key={line.key} className={`bubble ${line.who}`}>
              <span className="who">{line.who === 'you' ? 'You' : 'Agent'}</span>
              <p>{line.text}</p>
            </div>
          ))}
          {busy && <p className="hint">Agent is typing…</p>}
          <div ref={endRef} />
        </main>

        {approval && (
          <p className="notice" role="status">
            A refund of ${approval.amount.toFixed(2)} is waiting for staff approval. The agent will continue once
            it is decided.
          </p>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <form onSubmit={send}>
          <label htmlFor="message" className="visually-hidden">
            Your message
          </label>
          <input
            id="message"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={approval ? 'Waiting for staff approval…' : 'Type your message'}
            disabled={busy || approval !== null}
            maxLength={4000}
            autoComplete="off"
          />
          <button type="submit" disabled={busy || approval !== null || !draft.trim()}>
            Send
          </button>
        </form>
      </div>
      <ToolPanel messages={messages} />
    </div>
  )
}
