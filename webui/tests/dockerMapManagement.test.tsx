import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { api } from '../src/api/client'
import { DockerMapManagement } from '../src/pages/docker/DockerMapManagement'

vi.mock('../src/api/client', () => ({ api: vi.fn(), withOnlinePlayerGuard: (fn: (force: boolean) => unknown) => fn(false) }))
vi.mock('../src/components/MemoryBalancingControl', () => ({ MemoryBalancingControl: () => <p>Memory controls</p> }))
vi.mock('../src/pages/gameconfig/PerMapSettings', () => ({ PerMapSettings: ({ initialTarget }: { initialTarget: string }) => <p>Editing partition {initialTarget}</p> }))
const snapshot = () => ({
  metadata: { desiredState: 'running', plan: { maps: [{ map: 'Survival_1', partitions: [1], memoryBytes: 16 * 1024 ** 3, initialReplicas: 1 }, { map: 'DeepDesert_1', partitions: [8], memoryBytes: 16 * 1024 ** 3, initialReplicas: 0 }], games: [] }, services: [{ component: 'game-1', state: 'running', gameReady: true }] },
  resources: { host: { memoryBytes: 40 * 1024 ** 3, availableBytes: 20 * 1024 ** 3 }, memoryGiB: 38, reservedMemoryGiB: 16, serviceReserveGiB: 2 },
  modes: { Survival_1: 'core', DeepDesert_1: 'dynamic' }, samplesFresh: true, samples: { containers: [{ component: 'game-1', memory: { usedBytes: 10 * 1024 ** 3, limitBytes: 16 * 1024 ** 3, swapUsedBytes: null } }] },
})
afterEach(() => { cleanup(); sessionStorage.clear(); vi.clearAllMocks() })
describe('Map management', () => {
  it('shows the target restarting before its old ready process has stopped', async () => {
    vi.mocked(api).mockResolvedValue({...snapshot(),metadata:{...snapshot().metadata,operation:{action:'maps.restart',partition:1,phase:'running'}}})
    render(<DockerMapManagement />)
    expect(await screen.findByText('Restarting',{exact:true})).toBeInTheDocument()
  })
  it('keeps unsupported maps resource-only and opens Global defaults without partition controls', async () => {
    const s=snapshot()
    s.metadata.plan.maps.push({map:'Overmap',partitions:[2],memoryBytes:2*1024**3,initialReplicas:1})
    vi.mocked(api).mockResolvedValue(s)
    render(<DockerMapManagement />)
    fireEvent.click(await screen.findByRole('button',{name:'Edit resources'}))
    expect(screen.queryByText('Editing partition 2')).toBeNull()
    fireEvent.click(screen.getByRole('button',{name:'Global defaults',exact:true}))
    expect(await screen.findByText('Editing partition global')).toBeInTheDocument()
    expect(screen.queryByLabelText('Overmap RAM limit in GiB')).toBeNull()
  })
  it('keeps an action failure visible after a successful observation refresh', async () => {
    vi.mocked(api).mockImplementation(async (_path, options) => { if (options?.method === 'PUT') throw new Error('Mode could not be saved.'); return snapshot() as never })
    render(<DockerMapManagement />)
    fireEvent.change(await screen.findByLabelText('Deep Desert mode'), { target: { value: 'always-on' } })
    await screen.findByText('Mode could not be saved.')
    fireEvent.click(screen.getByRole('button', { name: 'Refresh', exact: true }))
    await waitFor(() => expect(vi.mocked(api).mock.calls.filter(([, options]) => !options?.method)).toHaveLength(2))
    expect(screen.getByRole('alert')).toHaveTextContent('Mode could not be saved.')
  })
  it('finishes the exact persisted partial RAM allocation rather than a new draft', async () => {
    vi.mocked(api).mockResolvedValue({ ...snapshot(), metadata: { ...snapshot().metadata, pendingMemoryChange: { map: 'DeepDesert_1', bytes: 12 * 1024 ** 3 } } })
    render(<DockerMapManagement />)
    fireEvent.click(await screen.findByRole('button', { name: 'Retry RAM allocation' }))
    await waitFor(() => expect(vi.mocked(api).mock.calls.some(([, options]) => options?.method === 'PUT')).toBe(true))
    const write = vi.mocked(api).mock.calls.find(([, options]) => options?.method === 'PUT')!
    expect(JSON.parse(String(write[1]?.body))).toEqual({ setting: 'memory', map: 'DeepDesert_1', memoryGiB: 12 })
  })
  it('does not present partial map samples as complete usage', async () => {
    const data = snapshot()
    data.metadata.plan.maps[0].partitions.push(9)
    data.metadata.services.push({ component: 'game-9', state: 'running', gameReady: true })
    vi.mocked(api).mockResolvedValue(data)
    render(<DockerMapManagement />)
    await screen.findByText('At least 10.0 GiB used / 32.0 GiB combined limit')
    expect(screen.getByText('1 of 2 running maps measured')).toBeInTheDocument()
    expect(screen.getByText('Players unknown')).toBeInTheDocument()
  })
  it('shows host swap consumption separately from the map policy', async () => {
    const data = { ...snapshot(), resources: { ...snapshot().resources, host: { ...snapshot().resources.host, swapTotalBytes: 10 * 1024 ** 3, swapFreeBytes: 8 * 1024 ** 3 } } }
    vi.mocked(api).mockResolvedValue(data)
    render(<DockerMapManagement />)
    await screen.findByText('2.0 GiB used')
    expect(screen.getByText('8.0 GiB available · shared by the host')).toBeInTheDocument()
  })
  it('shows measured RAM separately from the ceiling and unknown swap honestly', async () => {
    vi.mocked(api).mockResolvedValue(snapshot())
    render(<DockerMapManagement />)
    await screen.findByText('10.0 GiB used / 16.0 GiB limit per map')
    expect(screen.getByText('Swap used: not reported by Docker')).toBeInTheDocument()
    expect(screen.getByText('Unallocated · saved limit 16.0 GiB')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'Edit settings' })[1])
    expect(screen.getByText('Editing partition 8')).toBeInTheDocument()
  })
  it('saves lifecycle mode directly and keeps existing tools available', async () => {
    vi.mocked(api).mockResolvedValue(snapshot())
    render(<DockerMapManagement legacyTools={<p>Existing detailed map tools</p>} />)
    fireEvent.change(await screen.findByLabelText('Deep Desert mode'), { target: { value: 'overmap-active' } })
    await waitFor(() => expect(vi.mocked(api).mock.calls.some(([, options]) => options?.method === 'PUT')).toBe(true))
    const write = vi.mocked(api).mock.calls.find(([, options]) => options?.method === 'PUT')!
    expect(JSON.parse(String(write[1]?.body))).toEqual({ setting: 'mode', map: 'DeepDesert_1', mode: 'overmap-active' })
    fireEvent.click(screen.getByRole('button', { name: 'Additional map tools' }))
    expect(screen.getByText('Existing detailed map tools')).toBeInTheDocument()
  })
  it('does not present stale measurements as live usage', async () => {
    vi.mocked(api).mockResolvedValue({ ...snapshot(), samplesFresh: false })
    render(<DockerMapManagement />)
    await screen.findByText(/Memory samples are unavailable/)
    expect(screen.getByText('Usage unknown / 16.0 GiB limit per map')).toBeInTheDocument()
    expect(screen.queryByText('10.0 GiB used / 16.0 GiB limit per map')).not.toBeInTheDocument()
  })
  it('does not interpret a failed Docker sample as zero usage', async () => {
    vi.mocked(api).mockResolvedValue({ ...snapshot(), samples: { containers: [{ component: 'game-1', memory: null }] } })
    render(<DockerMapManagement />)
    await screen.findByText('Usage unknown / 16.0 GiB limit per map')
    expect(screen.getByText('0 of 1 running maps measured')).toBeInTheDocument()
  })
  it('does not call a ready map loading because another partition is intentionally cold', async () => {
    const data = snapshot()
    data.metadata.plan.maps[0].partitions.push(9)
    vi.mocked(api).mockResolvedValue(data)
    render(<DockerMapManagement />)
    expect(await screen.findByText('Ready', { exact: true })).toBeInTheDocument()
    expect(screen.queryByText('Loading', { exact: true })).not.toBeInTheDocument()
  })
})
