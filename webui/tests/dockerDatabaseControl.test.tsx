import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { DockerDatabaseControl } from '../src/pages/docker/DockerDatabaseControl'
import { api } from '../src/api/client'
vi.mock('../src/api/client', () => ({ api: vi.fn() }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const stopped = { phase: 'database-ready', desiredState: 'stopped', database: { state: 'exited', health: 'unknown' }, services: [{ state: 'created' }], backups: [] }
it('starts only the database and waits for its recorded operation', async () => {
  let started = false
  vi.mocked(api).mockImplementation(async (_path, init) => {
    if (init?.method === 'POST') { started = true; return { ok: true, data: { ...stopped, operation: { id: 'one', phase: 'running' } } } as never }
    return { ok: true, data: started ? { ...stopped, database: { state: 'running', health: 'healthy' }, operation: { id: 'one', phase: 'completed' } } : stopped } as never
  })
  const changed = vi.fn()
  render(<DockerDatabaseControl onChanged={changed} />)
  const button = await screen.findByRole('button', { name: 'Start database' })
  await waitFor(() => expect(button).toBeEnabled());fireEvent.click(button)
  await waitFor(() => expect(changed).toHaveBeenCalledOnce())
  expect(screen.getByRole('button', { name: 'Stop database' })).toBeEnabled()
  const writes = vi.mocked(api).mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(writes).toEqual([['/api/docker/setup', { method: 'POST', body: JSON.stringify({ action: 'database.start' }) }]])
})
it('keeps database stop disabled while a battlegroup service is running', async () => {
  vi.mocked(api).mockResolvedValue({ ok: true, data: { ...stopped, database: { state: 'running', health: 'healthy' }, services: [{ state: 'running' }] } })
  render(<DockerDatabaseControl onChanged={vi.fn()} />)
  expect(await screen.findByRole('button', { name: 'Stop database' })).toBeDisabled()
})
