// @vitest-environment jsdom
import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from './App'

afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.unstubAllGlobals()
})

test('execution details show persisted node data and retry failed executions', async () => {
  localStorage.setItem('flowforge-token', 'test-token')
  const failedExecution = {
    id: 'run-old-1234', workflow_id: 'flow-1', workflow_version_id: 'version-1', status: 'failed',
    trigger_input: { requested: true }, error: 'temporary network error', retry_count: 0,
    created_at: '2026-01-01T00:00:00Z', started_at: '2026-01-01T00:00:00Z', finished_at: '2026-01-01T00:00:02Z',
    nodes: [{ id: 'node-record-1', node_id: 'request-1', node_type: 'http-request', status: 'failed', input: { url: 'https://example.com' }, error: 'temporary network error', retry_count: 1, duration_ms: 180 }],
  }
  const workflow = { id: 'flow-1', name: 'Inventory check', definition: { nodes: [], edges: [] }, enabled: true, updated_at: '2026-01-01T00:00:00Z' }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/auth/me')) return new Response(JSON.stringify({ id: 'user-1', email: 'operator@example.com', organization_id: 'org-1' }), { status: 200 })
    if (url.endsWith('/workflows/flow-1')) return new Response(JSON.stringify(workflow), { status: 200 })
    if (url.endsWith('/executions/run-old-1234')) return new Response(JSON.stringify(failedExecution), { status: 200 })
    if (url.endsWith('/executions/run-old-1234/retry') && init?.method === 'POST') return new Response(JSON.stringify({ id: 'run-new-5678', status: 'pending', retry_count: 1 }), { status: 202 })
    if (url.endsWith('/executions/run-new-5678')) return new Response(JSON.stringify({ ...failedExecution, id: 'run-new-5678', status: 'pending', nodes: [], error: null }), { status: 200 })
    return new Response(JSON.stringify({ detail: `Unexpected request: ${url}` }), { status: 404 })
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<MemoryRouter initialEntries={['/executions/run-old-1234']}><App /></MemoryRouter>)
  expect(await screen.findByText('Inventory check')).toBeTruthy()
  expect(await screen.findByText('http request')).toBeTruthy()
  expect(screen.getByText(/https:\/\/example\.com/)).toBeTruthy()
  expect(screen.getAllByText('temporary network error')).toHaveLength(2)
  fireEvent.click(screen.getByRole('button', { name: /retry run/i }))
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/executions/run-old-1234/retry'), expect.objectContaining({ method: 'POST', headers: expect.any(Object) })))
  expect(await screen.findByText('run-new-5678')).toBeTruthy()
})
