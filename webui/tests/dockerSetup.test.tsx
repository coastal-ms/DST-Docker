import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import DockerSetup from '../src/pages/docker/DockerSetup'
import { api } from '../src/api/client'

vi.mock('../src/api/client', () => ({ api: vi.fn() }))
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers() })

it.each([
  ['exited', 'unhealthy', 'Stopped'],
  ['created', 'healthy', 'Stopped'],
  ['running', 'unhealthy', 'unhealthy'],
  ['running', 'healthy', 'healthy'],
])('reports database lifecycle %s before its cached health %s', async (state, health, displayed) => {
  vi.mocked(api).mockResolvedValue({ ok: true, data: {
    phase: 'database-ready', assets: { state: 'downloaded', images: [] }, credentialsSaved: false,
    database: { name: 'fixture', port: 18932, state, health }, profile: null,
    partitionsPrepared: false, connectionServices: [], services: [], plan: null,
    desiredState: 'stopped', operation: null,
  } } as never)
  render(<DockerSetup />)
  const label = await screen.findByText('Health', { exact: true })
  expect(label.nextElementSibling).toHaveTextContent(displayed)
  expect(vi.mocked(api).mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
})

it('unlocks database setup when the installer finishes downloading without a page reload', async () => {
  vi.useFakeTimers()
  const state = { phase: 'new', assets: { state: 'not-installed', images: [] }, database: null,
    credentialsSaved: false, profile: null, partitionsPrepared: false, connectionServices: [],
    services: [], plan: null, desiredState: 'stopped', operation: null }
  vi.mocked(api).mockResolvedValue({ ok: true, data: state } as never)
  await act(async () => { render(<DockerSetup />) })
  expect(screen.getByRole('button', { name: 'Create database' })).toBeDisabled()
  expect(screen.getByText(/Check the installer terminal/)).toBeInTheDocument()
  vi.mocked(api).mockResolvedValue({ ok: true, data: { ...state, assets: { state: 'downloaded', images: [] } } } as never)
  await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
  expect(screen.getByRole('button', { name: 'Create database' })).toBeEnabled()
  expect(screen.getByText('Downloaded and verified.')).toBeInTheDocument()
})
