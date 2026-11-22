import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import DockerFirstRun from '../src/pages/docker/DockerFirstRun'
import { prepareFirstWorld, setupComplete } from '../src/pages/docker/firstRun'
import type { SetupState } from '../src/pages/docker/DockerSetup'
import { api } from '../src/api/client'
import { BrowserRouter } from '../src/router'

vi.mock('../src/api/client', () => ({ api: vi.fn() }))
const fresh = (): SetupState => ({ phase: 'new', assets: { state: 'downloaded', images: [] }, database: null, profile: null, credentialsSaved: false, partitionsPrepared: false, connectionServices: [], services: [], plan: null, desiredState: 'stopped', operation: null })
const prepared = (): SetupState => ({ ...fresh(), profile: { name: 'Test world', region: 'Europe', address: 'example.test', gamePortBase: 7777 }, partitionsPrepared: true, services: ['director', 'gateway', 'text-router', 'game-1'].map(component => ({ component, phase: 'prepared', state: 'exited' })) })
const details = { name: 'Test world', region: 'Europe', address: 'example.test', gamePortBase: 7777, port: 18932, token: 'synthetic-service-token' }
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers(); window.history.replaceState({}, '', '/') })
function mockWorld(initial = fresh(), fail?: string, network = '') {
  let current = initial
  const actions: string[] = []
  vi.mocked(api).mockImplementation(async (_path, init) => {
    if (_path === '/api/docker/network') return { dockerIp: network } as never
    if (init?.method === 'POST') {
      const request = JSON.parse(init.body as string)
      actions.push(request.action)
      if (request.action === fail) return { ok: false, error: 'A useful setup error' } as never
      switch (request.action) {
        case 'credentials.save': current = { ...current, credentialsSaved: true }; break
        case 'database.create': current = { ...current, phase: 'database-starting', database: { name: 'fixture', port: request.port, state: 'running', health: 'healthy' } }; break
        case 'database.initialize': current = { ...current, phase: 'database-initialized' }; break
        case 'database.migrate': current = { ...current, phase: 'database-ready' }; break
        case 'world.configure': current = { ...current, profile: request.profile, partitionsPrepared: true }; break
        case 'services.prepare': current = { ...current, services: prepared().services }; break
      }
    }
    return { ok: true, data: current } as never
  })
  return actions
}
function renderGate(canSetup = true) { return render(<BrowserRouter><DockerFirstRun canSetup={canSetup}><nav>Management navigation</nav></DockerFirstRun></BrowserRouter>) }
async function worldForm(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole('button', { name: 'Next', exact: true })
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
}
async function reviewWorld(user: ReturnType<typeof userEvent.setup>) {
  await worldForm(user)
  await user.selectOptions(screen.getByLabelText('Player access'), 'public')
  await user.type(screen.getByLabelText('Server address'), 'example.test')
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
  await user.type(screen.getByLabelText('Funcom service token'), details.token)
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
}

it('gates a fresh install and direct management links without making writes', async () => {
  window.history.replaceState({}, '', '/settings')
  const actions = mockWorld()
  renderGate()
  expect(screen.queryByText('Management navigation')).not.toBeInTheDocument()
  await screen.findByRole('button', { name: 'Next', exact: true })
  expect(window.location.pathname).toBe('/setup')
  expect(screen.queryByText('Management navigation')).not.toBeInTheDocument()
  expect(actions).toEqual([])
})
it('retains management for an established stopped world even with missing credentials and unavailable assets', async () => {
  const state = { ...prepared(), assets: { state: 'failed', images: [] } }
  expect(setupComplete(state)).toBe(true)
  mockWorld(state); renderGate()
  expect(await screen.findByRole('navigation')).toBeInTheDocument()
})
it('fails closed on a connection error and supports retry', async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error('Connection unavailable'))
  renderGate()
  expect(await screen.findByRole('alert')).toHaveTextContent('Connection unavailable')
  expect(screen.queryByText('Management navigation')).not.toBeInTheDocument()
  mockWorld()
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(await screen.findByRole('button', { name: 'Next', exact: true })).toBeInTheDocument()
})
it('asks an administrator to wait for the owner without exposing setup controls', async () => {
  const actions = mockWorld(); renderGate(false)
  await screen.findByText('Your server needs setup')
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Set up my server/ })).not.toBeInTheDocument()
  expect(actions).toEqual([])
})
it('prepares all required steps once and waits for explicit completion before showing the portal', async () => {
  const actions = mockWorld(); renderGate()
  const user = userEvent.setup()
  await reviewWorld(user)
  expect(actions).toEqual([])
  expect(screen.getByRole('heading', { name: 'Review your server' })).toBeInTheDocument()
  expect(screen.queryByText(details.token)).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Prepare server', exact: true }))
  await screen.findByRole('heading', { name: 'Your world is ready' })
  expect(actions).toEqual(['credentials.save', 'database.create', 'database.initialize', 'database.migrate', 'world.configure', 'services.prepare'])
  expect(screen.queryByText('Management navigation')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /Open management portal/ }))
  expect(await screen.findByRole('navigation')).toBeInTheDocument()
  expect(window.location.pathname).toBe('/')
})
it('resumes existing storage and world details without replacing them', async () => {
  const actions = mockWorld({ ...fresh(), phase: 'database-ready', database: { name: 'existing', port: 19000, state: 'running', health: 'healthy' }, credentialsSaved: true, partitionsPrepared: true, profile: prepared().profile })
  await prepareFirstWorld(details, vi.fn(), new AbortController().signal)
  expect(actions).toEqual(['services.prepare'])
})
it('does not replay an uncertain write or continue after a failure', async () => {
  const actions = mockWorld(fresh(), 'database.initialize')
  await expect(prepareFirstWorld(details, vi.fn(), new AbortController().signal)).rejects.toThrow('A useful setup error')
  expect(actions).toEqual(['credentials.save', 'database.create', 'database.initialize'])
})
it('does not report success when a failed preparation already left prepared container records', async () => {
  const state = { ...prepared(), phase: 'database-ready', credentialsSaved: true,
    database: { name: 'db', port: 18932, state: 'running', health: 'healthy' },
    operation: { action: 'services.prepare', phase: 'failed', error: 'Docker operation failed (404).' } }
  const actions: string[] = []
  vi.mocked(api).mockImplementation(async (_path, init) => {
    if (init?.method === 'POST') actions.push(JSON.parse(init.body as string).action)
    return { ok: true, data: state } as never
  })
  await expect(prepareFirstWorld(details, vi.fn(), new AbortController().signal)).rejects.toThrow('Docker operation failed (404).')
  expect(actions).toEqual(['services.prepare'])
})
it('observes an in-flight operation after reload without starting more work', async () => {
  vi.useFakeTimers()
  const actions = mockWorld({ ...fresh(), operation: { action: 'database.create', phase: 'running' } })
  await act(async () => { renderGate() })
  expect(screen.getByRole('button', { name: 'Preparing…' })).toBeDisabled()
  await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
  expect(actions).toEqual([])
})
it('unlocks setup automatically when the installer finishes downloading', async () => {
  vi.useFakeTimers()
  mockWorld({ ...fresh(), assets: { state: 'downloading', images: [] } })
  await act(async () => { renderGate() })
  await act(async () => { screen.getByRole('button', { name: 'Next', exact: true }).click() })
  expect(screen.getByText('Downloading…')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Next', exact: true })).toBeDisabled()
  await act(async () => { screen.getByRole('button', { name: 'Next', exact: true }).closest('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
  expect(screen.getByRole('heading', { name: 'Check your installation' })).toBeInTheDocument()
  mockWorld()
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(screen.getByText('Downloaded and verified')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Next', exact: true })).toBeEnabled()
})
it('validates each stage, keeps entries on Back and blocks skipping ahead', async () => {
  const actions = mockWorld(); renderGate()
  const user = userEvent.setup()
  await worldForm(user)
  await user.selectOptions(screen.getByLabelText('Player access'), 'public')
  expect(screen.getByRole('button', { name: /6\. Review/ })).toBeDisabled()
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
  expect(screen.getByRole('heading', { name: 'Give your world an identity' })).toBeInTheDocument()
  await user.type(screen.getByLabelText('Server address'), 'example.test')
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
  expect(screen.getByRole('heading', { name: 'Connect to Funcom' })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
  expect(screen.getByRole('heading', { name: 'Connect to Funcom' })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Back' }))
  expect(screen.getByLabelText('Server address')).toHaveValue('example.test')
  expect(actions).toEqual([])
})
it('requires a private address for Private / LAN and preserves it in the prepared world', async () => {
  const actions = mockWorld(); renderGate()
  const user = userEvent.setup()
  await worldForm(user)
  expect(screen.getByLabelText('Player access')).toHaveValue('private')
  expect(screen.getByLabelText('Server address')).toBeRequired()
  await user.type(screen.getByLabelText('Server address'), '8.8.8.8')
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
  expect(screen.getByRole('alert')).toHaveTextContent('Private / LAN requires a private or loopback IPv4 address')
  expect(actions).toEqual([])
  await user.clear(screen.getByLabelText('Server address'))
  await user.type(screen.getByLabelText('Server address'), '192.168.1.50')
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
  await user.type(screen.getByLabelText('Funcom service token'), details.token)
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
  expect(screen.getByText('Private / LAN', { exact: true })).toBeInTheDocument()
  expect(screen.getByText('192.168.1.50', { exact: true })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Prepare server', exact: true }))
  await screen.findByRole('heading', { name: 'Your world is ready' })
  const configured = vi.mocked(api).mock.calls.find(([, init]) => init?.method === 'POST' && JSON.parse(init.body as string).action === 'world.configure')
  expect(JSON.parse(configured![1]!.body as string).profile.address).toBe('192.168.1.50')
})
it('does not label a private address as Public / External', async () => {
  const actions = mockWorld(); renderGate()
  const user = userEvent.setup()
  await worldForm(user)
  await user.selectOptions(screen.getByLabelText('Player access'), 'public')
  await user.type(screen.getByLabelText('Server address'), '10.0.0.5')
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
  expect(screen.getByRole('alert')).toHaveTextContent('Choose Private / LAN')
  expect(actions).toEqual([])
})
it('shows and fills the detected Docker IP for a fresh Private / LAN world', async () => {
  const actions = mockWorld(fresh(), undefined, '172.25.199.100'); renderGate()
  const user = userEvent.setup()
  await worldForm(user)
  await waitFor(() => expect(screen.getByLabelText('Server address')).toHaveValue('172.25.199.100'))
  expect(screen.getByText('172.25.199.100', { exact: true })).toBeVisible()
  expect(actions).toEqual([])
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
  await user.type(screen.getByLabelText('Funcom service token'), details.token)
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
  expect(screen.getByText('172.25.199.100', { exact: true })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Prepare server', exact: true }))
  await screen.findByRole('heading', { name: 'Your world is ready' })
  const configured = vi.mocked(api).mock.calls.find(([, init]) => init?.method === 'POST' && JSON.parse(init.body as string).action === 'world.configure')
  expect(JSON.parse(configured![1]!.body as string).profile.address).toBe('172.25.199.100')
})
it('fills the detected public IPv4 and lets the owner use a hostname instead', async () => {
  const actions = mockWorld(fresh(), undefined, '172.25.199.100')
  const setupApi = vi.mocked(api).getMockImplementation()!
  vi.mocked(api).mockImplementation(async (path, init) => path === '/api/docker/network/public-ip'
    ? { publicIp: '8.8.4.4' } : setupApi(path, init))
  renderGate()
  const user = userEvent.setup()
  await worldForm(user)
  const address = screen.getByLabelText('Server address')
  const access = screen.getByLabelText('Player access')
  await user.clear(address)
  await user.type(address, '192.168.1.50')
  await user.selectOptions(access, 'public')
  await waitFor(() => expect(address).toHaveValue('8.8.4.4'))
  await user.clear(address)
  await user.type(address, 'world.example.test')
  expect(address).toHaveValue('world.example.test')
  await user.selectOptions(access, 'private')
  expect(address).toHaveValue('192.168.1.50')
  await user.selectOptions(access, 'public')
  expect(address).toHaveValue('world.example.test')
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
  expect(screen.getByRole('heading', { name: 'Connect to Funcom' })).toBeInTheDocument()
  expect(actions).toEqual([])
})
it('keeps a manually entered public address when detection finishes later', async () => {
  mockWorld()
  const setupApi = vi.mocked(api).getMockImplementation()!
  let finish!: (value: { publicIp: string }) => void
  vi.mocked(api).mockImplementation((path, init) => path === '/api/docker/network/public-ip'
    ? new Promise(resolve => { finish = resolve }) : setupApi(path, init))
  renderGate()
  const user = userEvent.setup()
  await worldForm(user)
  await user.selectOptions(screen.getByLabelText('Player access'), 'public')
  const address = screen.getByLabelText('Server address')
  await user.type(address, 'world.example.test')
  await act(async () => { finish({ publicIp: '8.8.4.4' }) })
  expect(address).toHaveValue('world.example.test')
})
it('preserves an address typed before detection finishes', async () => {
  mockWorld()
  const setupApi = vi.mocked(api).getMockImplementation()!
  let finish!: (value: never) => void
  vi.mocked(api).mockImplementation((path, init) => path === '/api/docker/network' ? new Promise(resolve => { finish = resolve }) : setupApi(path, init))
  renderGate()
  const user = userEvent.setup()
  await worldForm(user)
  await user.type(screen.getByLabelText('Server address'), '192.168.1.50')
  await act(async () => { finish({ dockerIp: '172.25.199.100' } as never) })
  expect(screen.getByText('172.25.199.100', { exact: true })).toBeInTheDocument()
  expect(screen.getByLabelText('Server address')).toHaveValue('192.168.1.50')
})
it('does not fill a private IP into Public / External when detection completes late', async () => {
  mockWorld()
  const setupApi = vi.mocked(api).getMockImplementation()!
  let finish!: (value: never) => void
  vi.mocked(api).mockImplementation((path, init) => path === '/api/docker/network' ? new Promise(resolve => { finish = resolve }) : setupApi(path, init))
  renderGate()
  const user = userEvent.setup()
  await worldForm(user)
  await user.selectOptions(screen.getByLabelText('Player access'), 'public')
  await act(async () => { finish({ dockerIp: '172.25.199.100' } as never) })
  expect(screen.getByLabelText('Server address')).toHaveValue('')
  await user.selectOptions(screen.getByLabelText('Player access'), 'private')
  expect(screen.getByLabelText('Server address')).toHaveValue('172.25.199.100')
})
it('preserves a saved address when another Docker IP is detected', async () => {
  mockWorld({ ...fresh(), profile: { ...prepared().profile!, address: '192.168.1.50' } }, undefined, '172.25.199.100')
  renderGate()
  const user = userEvent.setup()
  await worldForm(user)
  await screen.findByText('172.25.199.100', { exact: true })
  expect(screen.getByLabelText('Server address')).toHaveValue('192.168.1.50')
})
it('offers retry after detection fails and still accepts a manually supplied address', async () => {
  mockWorld(); renderGate()
  const user = userEvent.setup()
  await worldForm(user)
  const retry = await screen.findByRole('button', { name: 'Retry IP detection' })
  mockWorld(fresh(), undefined, '172.25.199.100')
  await user.click(retry)
  await waitFor(() => expect(screen.getByLabelText('Server address')).toHaveValue('172.25.199.100'))
  await user.clear(screen.getByLabelText('Server address'))
  await user.type(screen.getByLabelText('Server address'), '192.168.1.50')
  await user.click(screen.getByRole('button', { name: 'Next', exact: true }))
  expect(screen.getByRole('heading', { name: 'Connect to Funcom' })).toBeInTheDocument()
})
it('keeps failed preparation on the preparation stage without retrying automatically', async () => {
  const actions = mockWorld(fresh(), 'database.initialize'); renderGate()
  const user = userEvent.setup()
  await reviewWorld(user)
  await user.click(screen.getByRole('button', { name: 'Prepare server', exact: true }))
  expect(await screen.findByRole('alert')).toHaveTextContent('A useful setup error')
  expect(screen.getByRole('heading', { name: 'Preparing your server' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Continue setup' })).toBeEnabled()
  expect(actions).toEqual(['credentials.save', 'database.create', 'database.initialize'])
})
it('waits for async preparation to complete before advancing', async () => {
  vi.useFakeTimers()
  const actions: string[] = []
  let current = { ...fresh(), credentialsSaved: true, phase: 'database-ready', database: { name: 'db', port: 18932, state: 'running', health: 'healthy' }, profile: prepared().profile, partitionsPrepared: true }
  vi.mocked(api).mockImplementation(async (_path, init) => {
    if (init?.method === 'POST') { actions.push(JSON.parse(init.body as string).action); return { ok: true, data: { ...current, operation: { action: 'services.prepare', phase: 'running' } } } as never }
    return { ok: true, data: current } as never
  })
  let finished = false
  const result = prepareFirstWorld(details, vi.fn(), new AbortController().signal).then(() => { finished = true })
  await vi.advanceTimersByTimeAsync(0)
  expect(finished).toBe(false)
  current = { ...current, services: prepared().services }
  await vi.advanceTimersByTimeAsync(1500)
  await result
  expect(actions).toEqual(['services.prepare'])
})
