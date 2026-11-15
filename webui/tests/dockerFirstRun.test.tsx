import { act, cleanup, render, screen } from '@testing-library/react'
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
function mockWorld(initial = fresh(), fail?: string) {
  let current = initial
  const actions: string[] = []
  vi.mocked(api).mockImplementation(async (_path, init) => {
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
  mockWorld()
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(screen.getByText('Downloaded and verified')).toBeInTheDocument()
})
it('validates each stage, keeps entries on Back and blocks skipping ahead', async () => {
  const actions = mockWorld(); renderGate()
  const user = userEvent.setup()
  await worldForm(user)
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
