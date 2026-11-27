import type { Message } from './api.ts'
import { formatResult, toolEvents } from './tools.ts'

/** Side panel: what the agent did behind the scenes (tool calls and their results). */
export default function ToolPanel({ messages }: { messages: Message[] }) {
  const events = toolEvents(messages)
  return (
    <aside className="tools" aria-label="Agent actions">
      <h2>Agent actions</h2>
      {events.length === 0 && <p className="hint">Tool calls will appear here.</p>}
      <ol>
        {events.map((e) => (
          <li key={e.id} className={e.result === null ? 'running' : e.ok ? 'ok' : 'failed'}>
            <details>
              <summary>
                <span className="status" aria-hidden="true">
                  {e.result === null ? '…' : e.ok ? '✓' : '✗'}
                </span>
                <code>{e.name}</code>
                <span className="visually-hidden">
                  {e.result === null ? '(running)' : e.ok ? '(succeeded)' : '(failed)'}
                </span>
              </summary>
              <p className="label">Arguments</p>
              <pre>{JSON.stringify(e.args, null, 2)}</pre>
              <p className="label">Result</p>
              <pre>{e.result === null ? 'waiting…' : formatResult(e.result)}</pre>
            </details>
          </li>
        ))}
      </ol>
    </aside>
  )
}
