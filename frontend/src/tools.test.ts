import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { Message } from './api.ts'
import { formatResult, toolEvents } from './tools.ts'

const convo: Message[] = [
  { role: 'user', content: 'cancel my order' },
  {
    role: 'assistant',
    content: null,
    tool_calls: [
      { id: 'a', name: 'find_user_id_by_email', args: { email: 'x@example.com' } },
      { id: 'b', name: 'get_order_details', args: { order_id: '#W1' } },
    ],
  },
  { role: 'tool', tool_call_id: 'b', name: 'get_order_details', content: 'Error: Authenticate the user first' },
  { role: 'tool', tool_call_id: 'a', name: 'find_user_id_by_email', content: 'sara_doe_496' },
  { role: 'assistant', content: 'Done.' },
  { role: 'assistant', content: null, tool_calls: [{ id: 'c', name: 'calculate', args: { expression: '1+1' } }] },
]

test('pairs calls with results by id, in call order', () => {
  const events = toolEvents(convo)
  assert.deepEqual(
    events.map((e) => [e.name, e.result, e.ok]),
    [
      ['find_user_id_by_email', 'sara_doe_496', true],
      ['get_order_details', 'Error: Authenticate the user first', false],
      ['calculate', null, true], // no result yet
    ],
  )
})

test('no tool calls -> no events', () => {
  assert.deepEqual(toolEvents([{ role: 'user', content: 'hi' }]), [])
})

test('formatResult pretty-prints JSON only', () => {
  assert.equal(formatResult('{"status":"pending"}'), '{\n  "status": "pending"\n}')
  assert.equal(formatResult('Transfer successful'), 'Transfer successful')
})
