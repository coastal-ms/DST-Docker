import { afterEach, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { api } from '../src/api/client'
import DockerNetworkCard from '../src/pages/docker/DockerNetworkCard'

vi.mock('../src/api/client', () => ({ api: vi.fn(), withOnlinePlayerGuard: (fn: (force: boolean) => Promise<unknown>) => fn(true) }))
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers(); localStorage.clear() })
const initial = { profile: { address: '192.168.1.5', gamePortBase: 28777 }, plan: { ports: { 'rmq-game': 29779 } }, desiredState: 'running', operation: null, services: [{}] }
it('switches to external access with the current-address guard and standard ports visible', async () => {
  vi.mocked(api).mockImplementation(async (_path, options) => ({ ok: true, data: options?.method === 'POST' ? {
    ...initial, profile: { address: '8.8.4.4', gamePortBase: 7777 }, plan: { ports: { 'rmq-game': 31982 } }, operation: { id: 'change', phase: 'completed', action: 'network.set' },
  } : initial }))
  render(<DockerNetworkCard />)
  expect(await screen.findByText('192.168.1.5')).toBeInTheDocument()
  expect(screen.getByText(/replace the old player ports/)).toHaveTextContent('29779')
  fireEvent.change(screen.getByLabelText('Player access'), { target: { value: 'public' } })
  fireEvent.change(screen.getByLabelText('Public IPv4 address'), { target: { value: '8.8.4.4' } })
  expect(screen.getByText(/Outside players connect/)).toHaveTextContent('TCP 31982 and UDP 7777–7810')
  fireEvent.click(screen.getByRole('button', { name: 'Apply player connections' }))
  fireEvent.click(screen.getByRole('button', { name: 'Apply and restart server' }))
  expect(await screen.findByText('Player connection settings applied.')).toBeInTheDocument()
  const call = vi.mocked(api).mock.calls.find(([, options]) => options?.method === 'POST')!
  expect(call[0]).toBe('/api/docker/setup?force=1')
  expect(JSON.parse(call[1]!.body as string)).toEqual({ action: 'network.set', mode: 'public', address: '8.8.4.4', expectedAddress: '192.168.1.5' })
})
it('shows a failed apply and keeps the address available for correction', async () => {
  vi.mocked(api).mockImplementation(async (path, options) => path.startsWith('/api/docker/host') ? { available: true, platform: 'wsl', target: '192.168.23.219' } : options?.method === 'POST' ? { ok: false, error: 'Public / External requires a public IPv4 address.' } : { ok: true, data: initial })
  render(<DockerNetworkCard />)
  await screen.findByText('192.168.1.5')
  fireEvent.change(screen.getByLabelText('Player access'), { target: { value: 'public' } })
  fireEvent.change(screen.getByLabelText('Public IPv4 address'), { target: { value: '192.168.1.6' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply player connections' }))
  fireEvent.click(screen.getByRole('button', { name: 'Apply and restart server' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('requires a public IPv4')
  expect(screen.getByLabelText('Public IPv4 address')).toHaveValue('192.168.1.6')
})
it('waits for the matching manager operation before reporting success', async () => {
  vi.useFakeTimers()
  let applied = false
  vi.mocked(api).mockImplementation(async (_path, options) => {
    if (options?.method === 'POST') return { ok: true, data: { ...initial, operation: { id: 'change', action: 'network.set', phase: 'running' } } }
    return { ok: true, data: applied ? { ...initial, profile: { address: '8.8.4.4', gamePortBase: 7777 }, plan: { ports: { 'rmq-game': 31982 } }, operation: { id: 'change', action: 'network.set', phase: 'completed' } } : initial }
  })
  await act(async () => { render(<DockerNetworkCard />) })
  await act(async () => {
    fireEvent.change(screen.getByLabelText('Player access'), { target: { value: 'public' } })
    fireEvent.change(screen.getByLabelText('Public IPv4 address'), { target: { value: '8.8.4.4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply player connections' }))
  })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Apply and restart server' }))
  })
  expect(screen.queryByText('Player connection settings applied.')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Applying…' })).toBeDisabled()
  expect(screen.getByLabelText('Player access')).toHaveValue('public')
  expect(screen.getByLabelText('Public IPv4 address')).toHaveValue('8.8.4.4')
  applied = true
  await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
  expect(screen.getByText('Player connection settings applied.')).toBeInTheDocument()
  expect(screen.getByText('8.8.4.4')).toBeInTheDocument()
})
it('automatically detects the public address when external access is selected', async () => {
  vi.mocked(api).mockImplementation(async path => path === '/api/docker/network/public-ip' ? { publicIp: '8.8.4.4' } : path.startsWith('/api/docker/network') ? { dockerIp: '192.168.23.220', routerForwardIp: '192.168.23.220', networkingMode: 'bridged' } : { ok: true, data: initial })
  render(<DockerNetworkCard />)
  await screen.findByText('192.168.1.5')
  fireEvent.change(screen.getByLabelText('Player access'), { target: { value: 'public' } })
  await waitFor(() => expect(screen.getByLabelText('Public IPv4 address')).toHaveValue('8.8.4.4'))
  expect(screen.getByRole('button', { name: 'Detect public IP' })).toBeEnabled()
  expect(await screen.findByText(/Forward router ports to/)).toHaveTextContent('192.168.23.220')
  expect(screen.getByLabelText('Public IPv4 address')).not.toHaveValue('192.168.23.220')
})
it('keeps the loopback card mounted when the delayed network response says native', async () => {
  let finish!: (value: { dockerIp: string; networkingMode: string }) => void
  vi.mocked(api).mockImplementation(async path => {
    if (path.startsWith('/api/docker/host')) return { available: true, platform: 'wsl', target: '192.168.23.219' }
    if (path.startsWith('/api/docker/network')) return new Promise(resolve => { finish = resolve })
    return { ok: true, data: { ...initial, profile: { address: '8.8.4.4', gamePortBase: 7777 } } }
  })
  render(<DockerNetworkCard />)
  await screen.findByRole('region', { name: 'Same-PC loopback target' })
  fireEvent.change(await screen.findByLabelText('Loopback target'), { target: { value: 'custom' } })
  fireEvent.change(screen.getByLabelText('Server IPv4 address'), { target: { value: '192.168.23.220' } })
  await waitFor(() => expect(finish).toBeTypeOf('function'))
  await act(async () => { finish({ dockerIp: '192.168.23.106', networkingMode: 'native' }) })
  expect(screen.getByRole('region', { name: 'Same-PC loopback target' })).toBeInTheDocument()
  expect(screen.getByLabelText('Server IPv4 address')).toHaveValue('192.168.23.220')
  expect(vi.mocked(api).mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true)
})
it('shows the existing Windows route while player access stays private', async () => {
  const route = '/api/docker/host?detail=loopback&publicIp=8.8.4.4'
  vi.mocked(api).mockImplementation(async path => {
    if (path === '/api/docker/network/public-ip') return { publicIp: '8.8.4.4' }
    if (path === route) return { available: true, platform: 'wsl', target: '192.168.23.219' }
    return { ok: true, data: initial }
  })
  render(<DockerNetworkCard />)
  expect(await screen.findByText('192.168.23.219')).toBeInTheDocument()
  expect(screen.getByLabelText('Player access')).toHaveValue('private')
  expect(screen.getByLabelText('LAN IPv4 address')).toHaveValue('192.168.1.5')
  expect(vi.mocked(api).mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true)
})
it('never overwrites a manual address when an earlier detection request returns', async () => {
  let finish!: (value: { publicIp: string }) => void
  vi.mocked(api).mockImplementation(async path => path === '/api/docker/network/public-ip' ? new Promise(resolve => { finish = resolve }) : { ok: true, data: initial })
  render(<DockerNetworkCard />)
  await screen.findByText('192.168.1.5')
  fireEvent.change(screen.getByLabelText('Player access'), { target: { value: 'public' } })
  fireEvent.change(screen.getByLabelText('Public IPv4 address'), { target: { value: '1.1.1.1' } })
  await act(async () => { finish({ publicIp: '8.8.4.4' }) })
  expect(screen.getByLabelText('Public IPv4 address')).toHaveValue('1.1.1.1')
})
it('restores a pending public target after reloading while the old private address is still active', async () => {
  vi.mocked(api).mockResolvedValue({ ok: true, data: { ...initial, desiredState: 'stopped', operation: { id: 'change', action: 'network.set', phase: 'running', stage: 'stopping', targetAddress: '8.8.4.4', targetMode: 'public', resume: true } } })
  render(<DockerNetworkCard />)
  await waitFor(() => expect(screen.getByLabelText('Player access')).toHaveValue('public'))
  expect(screen.getByLabelText('Public IPv4 address')).toHaveValue('8.8.4.4')
  expect(screen.getByRole('status')).toHaveTextContent('Stopping maps cleanly')
  expect(screen.queryByText('The game server will remain stopped after applying.')).not.toBeInTheDocument()
})
it('allows a public server to return to LAN access while keeping a stopped world stopped', async () => {
  vi.mocked(api).mockResolvedValue({ ok: true, data: { ...initial, desiredState: 'stopped', profile: { address: '8.8.4.4', gamePortBase: 7777 }, plan: { ports: { 'rmq-game': 31982 } } } })
  render(<DockerNetworkCard />)
  await waitFor(() => expect(screen.getByLabelText('Player access')).toHaveValue('public'))
  fireEvent.change(screen.getByLabelText('Player access'), { target: { value: 'private' } })
  expect(screen.getByLabelText('LAN IPv4 address')).toHaveValue('')
  expect(screen.getByText('The game server will remain stopped after applying.')).toBeInTheDocument()
})

it('does not change access or restart until confirmed, and cancellation keeps the draft', async () => {
  vi.mocked(api).mockResolvedValue({ ok: true, data: initial })
  render(<DockerNetworkCard />)
  await screen.findByText('192.168.1.5')
  fireEvent.change(screen.getByLabelText('Player access'), { target: { value: 'public' } })
  fireEvent.change(screen.getByLabelText('Public IPv4 address'), { target: { value: '8.8.4.4' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply player connections' }))
  expect(screen.getByRole('alertdialog')).toHaveTextContent('Connected players will be disconnected.')
  expect(screen.getByRole('alertdialog')).toHaveTextContent('8.8.4.4')
  expect(vi.mocked(api).mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Cancel', exact: true }))
  expect(screen.queryByRole('alertdialog')).toBeNull()
  expect(screen.getByLabelText('Public IPv4 address')).toHaveValue('8.8.4.4')
  expect(vi.mocked(api).mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false)
})
it('explains that applying access to a stopped server leaves it stopped', async () => {
  vi.mocked(api).mockResolvedValue({ ok: true, data: { ...initial, desiredState: 'stopped' } })
  render(<DockerNetworkCard />)
  await screen.findByText('192.168.1.5')
  fireEvent.change(screen.getByLabelText('Player access'), { target: { value: 'public' } })
  fireEvent.change(screen.getByLabelText('Public IPv4 address'), { target: { value: '8.8.4.4' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply player connections' }))
  expect(screen.getByRole('alertdialog')).toHaveTextContent('will remain stopped')
  expect(screen.getByRole('button', { name: 'Apply settings', exact: true })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Apply and restart server' })).toBeNull()
})
