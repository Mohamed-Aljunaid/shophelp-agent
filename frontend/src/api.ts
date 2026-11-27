// Client for the ShopHelp FastAPI backend (api/app.py).

// Dev: the API runs separately on :8000. Production build: served by the API itself (same origin).
export const API_URL: string = import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? 'http://localhost:8000' : '')

export type ToolCall = { id: string; name: string; args: Record<string, unknown> }

export type Message =
  | { role: 'user'; content: string }
  | { role: 'assistant'; content: string | null; tool_calls?: ToolCall[] }
  | { role: 'tool'; tool_call_id: string; name: string; content: string }

export type Approval = {
  id: string
  tool: string
  args: Record<string, unknown>
  amount: number
  threshold: number
  user_id: string
}

export type ChatResponse = {
  session_id: string
  reply: string | null
  messages: Message[]
  pending_approval: Approval | null
}

export type Session = {
  session_id: string
  user_id: string | null
  messages: Message[]
  pending_approval: Approval | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export function sendChat(message: string, sessionId: string | null): Promise<ChatResponse> {
  return request('/chat', { method: 'POST', body: JSON.stringify({ message, session_id: sessionId }) })
}

export function getSession(sessionId: string): Promise<Session> {
  return request(`/sessions/${encodeURIComponent(sessionId)}`)
}

// Staff endpoints: need the STAFF_TOKEN from the server's .env.

export type PendingApproval = Approval & { session_id: string; customer_message: string }

function staffHeaders(token: string) {
  return { 'X-Staff-Token': token }
}

export function listApprovals(token: string): Promise<PendingApproval[]> {
  return request('/approvals', { headers: staffHeaders(token) })
}

export function decideApproval(token: string, id: string, approved: boolean, note: string): Promise<ChatResponse> {
  return request(`/approvals/${encodeURIComponent(id)}`, {
    method: 'POST',
    headers: staffHeaders(token),
    body: JSON.stringify({ approved, note }),
  })
}
