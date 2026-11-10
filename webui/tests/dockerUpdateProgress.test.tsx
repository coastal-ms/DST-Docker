import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DockerUpdateProgress } from '../src/pages/commands/DockerUpdateProgress'
import { api } from '../src/api/client'

vi.mock('../src/api/client', () => ({ api: vi.fn() }))
const id = 'a'.repeat(32)
let running = true
beforeEach(() => {
  running = true
  vi.mocked(api).mockImplementation(async path => ({ available: true, operationId: id, build: '26547981',
    label: running ? 'Verifying backup' : 'Update complete', running, status: running ? 'running' : 'completed',
    events: [{ label: 'Creating backup', at: 100 }],
    output: String(path).includes('output=1') ? [{ name: 'Package download', text: 'Download 75% complete' }] : [],
  }))
})
afterEach(() => { cleanup(); vi.mocked(api).mockReset(); vi.useRealTimers() })

it('opens current output on demand and retains completed details after a page reopen', async () => {
  const view = render(<DockerUpdateProgress />)
  expect(await screen.findByText('Verifying backup')).toBeInTheDocument()
  expect(screen.queryByText('Download 75% complete')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Details', exact: true }))
  expect(await screen.findByText('Download 75% complete')).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Server update details' })).toBeInTheDocument()
  expect(vi.mocked(api).mock.calls.every(([, options]) => !options?.method || options.method === 'GET')).toBe(true)
  view.unmount(); running = false
  render(<DockerUpdateProgress />)
  expect(await screen.findByText('Update complete')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Details', exact: true }))
  expect(await screen.findByText('Download 75% complete')).toBeInTheDocument()
})

it('refreshes only while viewing a running update and stops after closing', async () => {
  vi.useFakeTimers()
  render(<DockerUpdateProgress operation={{ id, phase: 'running' }} />)
  await vi.advanceTimersByTimeAsync(0)
  fireEvent.click(screen.getByRole('button', { name: 'Details', exact: true }))
  await vi.advanceTimersByTimeAsync(0)
  const count = vi.mocked(api).mock.calls.length
  await vi.advanceTimersByTimeAsync(2500)
  expect(vi.mocked(api).mock.calls.length).toBeGreaterThan(count)
  fireEvent.click(screen.getByRole('button', { name: 'Hide details' }))
  await vi.advanceTimersByTimeAsync(0)
  const closed = vi.mocked(api).mock.calls.length
  await vi.advanceTimersByTimeAsync(6000)
  expect(vi.mocked(api).mock.calls.length).toBe(closed)
})

it('keeps failure output accessible and shows refresh errors', async () => {
  vi.mocked(api).mockResolvedValue({ available: true, operationId: id, label: 'Recovery needed', status: 'failed', running: false,
    error: 'Update failed; previous package restored.', events: [], output: [{ name: 'Database update', text: 'Migration failed' }] })
  render(<DockerUpdateProgress />)
  expect(await screen.findByText('Update failed; previous package restored.')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Details', exact: true }))
  expect(await screen.findByText('Migration failed')).toBeInTheDocument()
  vi.mocked(api).mockRejectedValue(new Error('Connection unavailable'))
  fireEvent.click(screen.getByRole('button', { name: 'Refresh details' }))
  await waitFor(() => expect(screen.getByText(/Progress could not be refreshed/)).toBeInTheDocument())
})
