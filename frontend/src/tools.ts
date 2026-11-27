// Turn conversation messages into tool-call events for the side panel.
// Kept free of React/Vite so `node --test` can run its tests directly.

import type { Message } from './api.ts'

export type ToolEvent = {
  id: string
  name: string
  args: Record<string, unknown>
  result: string | null // null = still running / no result yet
  ok: boolean
}

/** Every tool call in order, with its result matched by tool_call_id. */
export function toolEvents(messages: Message[]): ToolEvent[] {
  const results = new Map<string, string>()
  for (const m of messages) if (m.role === 'tool') results.set(m.tool_call_id, m.content)
  const events: ToolEvent[] = []
  for (const m of messages) {
    if (m.role !== 'assistant') continue
    for (const call of m.tool_calls ?? []) {
      const result = results.get(call.id) ?? null
      events.push({ id: call.id, name: call.name, args: call.args, result, ok: !result?.startsWith('Error:') })
    }
  }
  return events
}

/** Pretty-print JSON results; leave plain text as it is. */
export function formatResult(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text
  }
}
