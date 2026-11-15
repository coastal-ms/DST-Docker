import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { api } from '../src/api/client'
import DockerLanSettings from '../src/pages/docker/DockerLanSettings'
vi.mock('../src/api/client', () => ({ api: vi.fn() }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const initial = { available: true, platform: 'wsl', dockerIp: '172.25.1.2', windowsIp: '192.168.23.23', switchHint: 'Orbi Switch', networkingMode: 'nat', settings: { mode: 'nat', switch: '', address: '', prefix: 24 }, restartRequired: false }
it('stages a real dedicated LAN connection independently of the advertised public IP', async () => {
  vi.mocked(api).mockImplementation(async (_path, init) => init?.method === 'POST' ? { ...initial, settings: { mode: 'bridged', switch: 'Orbi Switch', address: '', prefix: 24 }, restartRequired: true, recoveryShortcut: 'recovery.cmd' } : initial)
  render(<DockerLanSettings />)
  await screen.findByLabelText('Host network mode')
  fireEvent.change(screen.getByLabelText('Host network mode'), { target: { value: 'bridged' } })
  expect(screen.getByLabelText('External switch name')).toHaveValue('Orbi Switch')
  expect(screen.getByLabelText('Get a LAN IP automatically (DHCP)')).toBeChecked()
  fireEvent.click(screen.getByRole('button', { name: 'Save Docker network' }))
  expect(await screen.findByText(/Network settings saved/)).toBeInTheDocument()
  expect(screen.getByText(/Host network change pending/)).toBeInTheDocument()
  const call = vi.mocked(api).mock.calls.find(([, init]) => init?.method === 'POST')!
  expect(JSON.parse(call[1]!.body as string)).toEqual({ action: 'network.settings.set', settings: { mode: 'bridged', switch: 'Orbi Switch', address: '', prefix: 24 } })
  expect(screen.getByText(/Recover Docker network/)).toBeInTheDocument()
})
it('lets the operator choose a dedicated address and prefix while showing an address-conflict error', async () => {
  vi.mocked(api).mockImplementation(async (_path, init) => { if (init?.method === 'POST') throw new Error('That LAN IP is already in use.'); return initial })
  render(<DockerLanSettings />)
  await screen.findByLabelText('Host network mode')
  fireEvent.change(screen.getByLabelText('Host network mode'), { target: { value: 'bridged' } })
  fireEvent.click(screen.getByLabelText('Get a LAN IP automatically (DHCP)'))
  fireEvent.change(screen.getByLabelText('Dedicated Docker IPv4'), { target: { value: '192.168.23.220' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save Docker network' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('already in use')
  expect(screen.getByLabelText('Dedicated Docker IPv4')).toHaveValue('192.168.23.220')
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save Docker network' })).toBeEnabled())
})
