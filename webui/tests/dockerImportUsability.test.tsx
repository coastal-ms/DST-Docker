import { cleanup, render, screen, fireEvent, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import DockerBackups from '../src/pages/docker/DockerBackups'
import DockerRestoreDialog from '../src/pages/docker/DockerRestoreDialog'
import { importDockerBackup } from '../src/api/docker'
import { api } from '../src/api/client'
vi.mock('../src/api/client', () => ({ api: vi.fn(), authenticatedApiNavigation: vi.fn(), withOnlinePlayerGuard: vi.fn() }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const original = 'My world 100% – 漢字.backup'
const named = { id: 'a'.repeat(32), name: 'backup-123-abcdef12.dump', originalFilename: original, phase: 'completed', createdAt: 1, bytes: 512, verification: { phase: 'completed' } }
const legacy = { id: 'b'.repeat(32), name: 'backup-122-abcdef12.dump', phase: 'completed', createdAt: 2, bytes: 512 }
it('shows original names and legacy fallback in the backup list and uses internal IDs for actions', async () => {
  vi.mocked(api).mockResolvedValue({ ok: true, data: { phase: 'database-ready', backups: [named, legacy], operation: null } } as never)
  render(<DockerBackups />)
  expect(await screen.findByText(original)).toBeInTheDocument()
  expect(screen.getByText(legacy.name)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Verify restore' }))
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(([, init]) => init?.method === 'POST' && JSON.parse(String(init.body)).backupId === legacy.id)).toBe(true))
})
it('labels restore choices with original filenames while retaining their internal IDs', async () => {
  vi.mocked(api).mockResolvedValue({ ok: true, data: { backups: [named] } } as never)
  render(<DockerRestoreDialog onClose={() => {}} onComplete={() => {}} />)
  expect(await screen.findByRole('option', { name: new RegExp('My world 100%') })).toHaveValue(named.id)
  expect(screen.getByRole('combobox')).toHaveValue(named.id)
})
it('transmits the original Unicode filename encoded once alongside the unmodified backup bytes', async () => {
  const id = 'a'.repeat(32)
  vi.mocked(api).mockResolvedValueOnce({ ok: true, uploadId: id } as never).mockResolvedValueOnce({ ok: true, data: { backups: [{ id, phase: 'completed' }] } } as never)
  const file = new File(['PGDMPfixture'], original)
  vi.spyOn(file, 'slice').mockReturnValue({ arrayBuffer: async () => new TextEncoder().encode('PGDMP').buffer } as Blob)
  await importDockerBackup(file)
  const [, init] = vi.mocked(api).mock.calls[0]
  expect(init?.body).toBe(file)
  expect(init?.headers).toMatchObject({ 'X-Dst-Backup-Filename': encodeURIComponent(original), 'X-Dst-Trusted-Backup': 'true' })
})
