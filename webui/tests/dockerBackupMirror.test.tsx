import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { DockerBackupMirror } from '../src/pages/docker/DockerBackupMirror'
import { api } from '../src/api/client'
vi.mock('../src/api/client', () => ({ api: vi.fn() }))
afterEach(() => { cleanup(); vi.clearAllMocks(); localStorage.clear() })
it('controls only the configured host mirror without a Windows folder picker or host path request', async () => {
  const mirror = { available: true, enabled: false, folder: '/home/tester/backups/world-one', phase: 'idle', protectedBackups: 0 }
  vi.mocked(api).mockImplementation(async (_path, init) => {
    if (init?.method === 'POST') mirror.enabled = JSON.parse(String(init.body)).enabled
    return { ok: true, data: { backupMirror: { ...mirror } } } as never
  })
  render(<DockerBackupMirror />)
  await screen.findByText('/home/tester/backups/world-one')
  fireEvent.click(screen.getByRole('checkbox', { name: 'Mirror backups to this folder' }))
  await waitFor(() => expect(screen.getByRole('checkbox')).toBeChecked())
  const writes = vi.mocked(api).mock.calls.filter(([, init]) => init?.method === 'POST')
  expect(writes).toEqual([['/api/docker/setup', { method: 'POST', body: JSON.stringify({ action: 'backups.mirror.set', enabled: true }) }]])
  expect(screen.queryByRole('button', { name: /Browse/ })).not.toBeInTheDocument()
  expect(vi.mocked(api).mock.calls.every(([path]) => path === '/api/docker/setup')).toBe(true)
})
it('shows explicit recovery while a failed copy protects its original backups', async () => {
  vi.mocked(api).mockResolvedValue({ ok: true, data: { backupMirror: { available: true, enabled: true, folder: '/copies/world', phase: 'failed', error: 'Copy needs review', protectedBackups: 2 } } })
  render(<DockerBackupMirror />)
  await screen.findByRole('button', { name: 'Retry copy' })
  expect(screen.getByRole('alert')).toHaveTextContent('Copy needs review')
  expect(screen.getByText(/keeps 2 source backup/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Copy now' })).toBeDisabled()
})
