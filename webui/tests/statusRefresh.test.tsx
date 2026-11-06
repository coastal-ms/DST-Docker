import { afterEach, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StatusProvider, useStatus } from '../src/hooks/useStatus'

const request = vi.hoisted(() => vi.fn())
vi.mock('../src/api/client', () => ({ api: request }))
vi.mock('../src/hooks/useInstallationMode', () => ({ useSoloInstallation: () => false }))
vi.mock('../src/hooks/useHealthRefresh', () => ({ useHealthRefreshPreset: () => ({ statusIntervalMs: 0 }) }))

afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllMocks() })

it('publishes the manual forced response immediately and rejects an older poll completing afterward', async () => {
  let finishPoll!: (value: unknown) => void
  const snapshot = (status: string) => ({
    ts: new Date().toISOString(), vm: { running: true },
    bg: { state: 'running' }, ports: { results: [{ port: 31982, status }] },
  })
  localStorage.setItem('dst.status.last.v1', JSON.stringify({ savedAt: Date.now(), status: snapshot('closed') }))
  request.mockImplementation((path: string) => {
    if (path === '/api/status') return new Promise(resolve => { finishPoll = resolve })
    if (path === '/api/status/refresh') return Promise.resolve(snapshot('open'))
    throw new Error(`Unexpected ${path}`)
  })
  function Consumer() {
    const status = useStatus()
    return <button onClick={() => void status.forceRefresh()}>{status.status?.ports?.results[0].status}</button>
  }
  render(<StatusProvider><Consumer /></StatusProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'closed' }))
  await waitFor(() => expect(screen.getByRole('button')).toHaveTextContent('open'))
  expect(request).toHaveBeenCalledWith('/api/status/refresh', { method: 'POST' })
  await act(async () => { finishPoll(snapshot('closed')) })
  expect(screen.getByRole('button')).toHaveTextContent('open')
  expect(request.mock.calls.filter(([path]) => path === '/api/status')).toHaveLength(1)
  expect(JSON.parse(localStorage.getItem('dst.status.last.v1')!).status.ports.results[0].status).toBe('open')
})

it('shows manual refresh progress, coalesces repeat clicks and surfaces failures without waiting for a poll', async () => {
  let rejectRefresh!: (error: Error) => void
  const snapshot = {ts: new Date().toISOString(), vm: {running:true}, ports:{results:[{port:31982,status:'unknown'}]}}
  request.mockImplementation((path: string) => path === '/api/status'
    ? Promise.resolve(snapshot)
    : new Promise((_resolve, reject) => { rejectRefresh = reject }))
  function Consumer() {
    const status = useStatus()
    return <><button onClick={() => void status.forceRefresh()}>Check now</button>
      <output>{status.loading ? 'Checking' : 'Idle'}</output>
      {status.error && <p role="alert">{status.error}</p>}</>
  }
  render(<StatusProvider><Consumer /></StatusProvider>)
  await screen.findByText('Idle')
  fireEvent.click(screen.getByRole('button', {name:'Check now'}))
  fireEvent.click(screen.getByRole('button', {name:'Check now'}))
  expect(screen.getByText('Checking')).toBeInTheDocument()
  expect(request.mock.calls.filter(([path]) => path === '/api/status/refresh')).toHaveLength(1)
  await act(async () => { rejectRefresh(new Error('Connection interrupted')) })
  expect(screen.getByRole('alert')).toHaveTextContent('Status refresh failed: Connection interrupted')
  expect(screen.getByText('Idle')).toBeInTheDocument()
})

it('clears a failed manual refresh after a later successful status request', async () => {
  let sequence = 0
  request.mockImplementation((path: string) => path === '/api/status'
    ? Promise.resolve({ ts: `2026-11-05T12:00:0${sequence++}Z`, vm: { running: true } })
    : Promise.reject(new Error('Connection interrupted')))
  function Consumer() {
    const status = useStatus()
    return <><button onClick={() => void status.forceRefresh()}>Force</button>
      <button onClick={() => void status.refresh()}>Poll</button>
      <output>{status.status?.ts}</output>
      {status.error && <p role="alert">{status.error}</p>}</>
  }
  render(<StatusProvider><Consumer /></StatusProvider>)
  await screen.findByText('2026-11-05T12:00:00Z')
  fireEvent.click(screen.getByRole('button', { name: 'Force' }))
  await screen.findByRole('alert')
  fireEvent.click(screen.getByRole('button', { name: 'Poll' }))
  await screen.findByText('2026-11-05T12:00:01Z')
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
})
