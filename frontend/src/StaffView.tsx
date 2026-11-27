import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { decideApproval, listApprovals, type PendingApproval } from './api.ts'

const TOKEN_KEY = 'shophelp-staff-token'
const POLL_MS = 5000

/** Staff page: refunds waiting for approval, with approve / reject buttons. */
export default function StaffView() {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) ?? '')
  const [tokenDraft, setTokenDraft] = useState('')
  const [items, setItems] = useState<PendingApproval[]>([])
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!token) return
    try {
      setItems(await listApprovals(token))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load approvals')
    }
  }, [token])

  useEffect(() => {
    const first = setTimeout(refresh, 0) // load now, then poll
    const timer = setInterval(refresh, POLL_MS)
    return () => {
      clearTimeout(first)
      clearInterval(timer)
    }
  }, [refresh])

  function signIn(e: FormEvent) {
    e.preventDefault()
    sessionStorage.setItem(TOKEN_KEY, tokenDraft.trim())
    setToken(tokenDraft.trim())
    setTokenDraft('')
  }

  function signOut() {
    sessionStorage.removeItem(TOKEN_KEY)
    setToken('')
    setItems([])
  }

  async function decide(item: PendingApproval, approved: boolean) {
    setBusyId(item.id)
    setMessage(null)
    try {
      await decideApproval(token, item.id, approved, notes[item.id] ?? '')
      setMessage(`${approved ? 'Approved' : 'Rejected'} $${item.amount.toFixed(2)} for ${item.user_id}.`)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not send the decision')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="staff">
      <header>
        <h1>ShopHelp · Staff approvals</h1>
        <a href="#">Back to chat</a>
      </header>

      {!token ? (
        <form onSubmit={signIn} className="token-form">
          <label htmlFor="token">Staff token</label>
          <input
            id="token"
            type="password"
            value={tokenDraft}
            onChange={(e) => setTokenDraft(e.target.value)}
            autoComplete="off"
          />
          <button type="submit" disabled={!tokenDraft.trim()}>
            Sign in
          </button>
        </form>
      ) : (
        <main>
          <div className="toolbar">
            <span>
              {items.length} waiting · refreshes every {POLL_MS / 1000}s
            </span>
            <button type="button" className="secondary" onClick={refresh}>
              Refresh
            </button>
            <button type="button" className="secondary" onClick={signOut}>
              Sign out
            </button>
          </div>

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {message && (
            <p className="notice" role="status">
              {message}
            </p>
          )}
          {items.length === 0 && !error && <p className="hint">No refunds are waiting for approval.</p>}

          <ul className="approvals">
            {items.map((item) => (
              <li key={item.id}>
                <p className="amount">
                  ${item.amount.toFixed(2)} <span>(limit ${item.threshold.toFixed(2)})</span>
                </p>
                <dl>
                  <dt>Customer</dt>
                  <dd>{item.user_id}</dd>
                  <dt>Action</dt>
                  <dd>
                    <code>{item.tool}</code>
                  </dd>
                  <dt>Details</dt>
                  <dd>
                    <pre>{JSON.stringify(item.args, null, 2)}</pre>
                  </dd>
                  <dt>Customer said</dt>
                  <dd>“{item.customer_message}”</dd>
                </dl>
                <label htmlFor={`note-${item.id}`}>Note for the agent (optional)</label>
                <input
                  id={`note-${item.id}`}
                  value={notes[item.id] ?? ''}
                  onChange={(e) => setNotes((n) => ({ ...n, [item.id]: e.target.value }))}
                  maxLength={1000}
                />
                <div className="actions">
                  <button type="button" onClick={() => decide(item, true)} disabled={busyId !== null}>
                    Approve
                  </button>
                  <button
                    type="button"
                    className="danger"
                    onClick={() => decide(item, false)}
                    disabled={busyId !== null}
                  >
                    Reject
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </main>
      )}
    </div>
  )
}
