import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { DockerBackupMirror } from '../src/pages/docker/DockerBackupMirror'
import { api } from '../src/api/client'
import { isWindowsViewer } from '../src/util/viewer'
vi.mock('../src/api/client', () => ({ api: vi.fn() }))
vi.mock('../src/util/viewer', () => ({ isWindowsViewer: vi.fn(() => true) }))
afterEach(() => { cleanup(); vi.clearAllMocks(); localStorage.clear(); vi.mocked(isWindowsViewer).mockReturnValue(true) })
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

it('copies the verified Windows Explorer path on Windows while retaining the Linux host path', async () => {
  const folder='/home/coastal/backups/world-one'
  const windowsFolder='\\\\wsl.localhost\\Ubuntu\\home\\coastal\\backups\\world-one'
  const writeText=vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText}})
  vi.mocked(api).mockResolvedValue({ok:true,data:{backupMirror:{available:true,enabled:true,folder,windowsFolder,phase:'idle',protectedBackups:0}}})
  render(<DockerBackupMirror />)
  await screen.findByText(windowsFolder)
  fireEvent.click(screen.getByRole('button',{name:'Copy folder path'}))
  await waitFor(()=>expect(writeText).toHaveBeenCalledWith(windowsFolder))
  expect(screen.getByText(folder)).toBeInTheDocument()
  expect(screen.getByText(/created when its first mirror copy starts/)).toBeInTheDocument()
})
it('keeps the real Linux path for non-Windows viewers', async () => {
  vi.mocked(isWindowsViewer).mockReturnValue(false)
  const folder='/home/test/backups/world-one'
  const writeText=vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText}})
  vi.mocked(api).mockResolvedValue({ok:true,data:{backupMirror:{available:true,enabled:true,folder,windowsFolder:'verified-windows-path',phase:'idle',protectedBackups:0}}})
  render(<DockerBackupMirror />)
  await screen.findByText(folder)
  fireEvent.click(screen.getByRole('button',{name:'Copy folder path'}))
  await waitFor(()=>expect(writeText).toHaveBeenCalledWith(folder))
})