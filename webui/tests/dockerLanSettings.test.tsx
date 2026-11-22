import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { api } from '../src/api/client'
import DockerLanSettings from '../src/pages/docker/DockerLanSettings'
vi.mock('../src/api/client', () => ({ api: vi.fn() }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const initial = { available: true, platform: 'wsl', dockerIp: '172.25.1.2', externalSwitches: ['LAN switch'], settings: { mode: 'nat', switch: '', address: '', prefix: 24 }, restartRequired: false }
it('stages a real dedicated LAN connection independently of the advertised public IP', async () => {
  vi.mocked(api).mockImplementation(async (_path, init) => init?.method === 'POST' ? { ...initial, settings: { mode: 'bridged', switch: 'LAN switch', address: '', prefix: 24 }, restartRequired: true, recoveryShortcut: 'recovery.cmd' } : initial)
  render(<DockerLanSettings />)
  await screen.findByLabelText('Host network mode')
  fireEvent.change(screen.getByLabelText('Host network mode'), { target: { value: 'bridged' } })
  expect(screen.getByLabelText('External switch')).toHaveValue('LAN switch')
  expect(screen.getByLabelText('Get a LAN IP automatically (DHCP)')).toBeChecked()
  fireEvent.click(screen.getByRole('button', { name: 'Save Docker network' }))
  expect(await screen.findByText(/Network settings saved/)).toBeInTheDocument()
  expect(screen.getByText(/Host network change pending/)).toBeInTheDocument()
  const call = vi.mocked(api).mock.calls.find(([, init]) => init?.method === 'POST')!
  expect(JSON.parse(call[1]!.body as string)).toEqual({ action: 'network.settings.set', settings: { mode: 'bridged', switch: 'LAN switch', address: '', prefix: 24 } })
  expect(screen.getByText(/Recover Docker network/)).toBeInTheDocument()
})

it('disables Own LAN address when no switch is available while allowing other modes', async () => {
  vi.mocked(api).mockResolvedValue({ ...initial, externalSwitches: [] })
  render(<DockerLanSettings />)
  const mode = await screen.findByLabelText('Host network mode')
  expect(screen.getByRole('option', { name: 'Own LAN address' })).toBeDisabled()
  expect(screen.getByText(/No external switches are available/)).toBeInTheDocument()
  fireEvent.change(mode, { target: { value: 'mirrored' } })
  expect(screen.getByRole('button', { name: 'Save Docker network' })).toBeEnabled()
})

it('prompts for a host restart when the running host predates switch detection', async () => {
  vi.mocked(api).mockResolvedValue({ ...initial, externalSwitches: undefined, switchHint: 'Ethernet' })
  render(<DockerLanSettings />)
  expect(await screen.findByText(/Shut down host/)).toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'Own LAN address' })).toBeDisabled()
  expect(screen.queryByText(/No external switches are available/)).not.toBeInTheDocument()
})

it('requires an explicit selection from the current list when the saved switch disappeared', async () => {
  vi.mocked(api).mockResolvedValue({ ...initial, externalSwitches: ['LAN switch', 'Other switch'], settings: { ...initial.settings, mode: 'bridged', switch: 'Ethernet' } })
  render(<DockerLanSettings />)
  const select = await screen.findByLabelText('External switch')
  const save = screen.getByRole('button', { name: 'Save Docker network' })
  expect(select).toHaveValue('')
  expect(screen.queryByRole('option', { name: 'Ethernet' })).not.toBeInTheDocument()
  expect(save).toBeDisabled()
  fireEvent.change(select, { target: { value: 'Other switch' } })
  expect(save).toBeEnabled()
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
