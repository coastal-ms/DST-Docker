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
  it('replaces queued-start feedback with the correlated failure instead of leaving a green request message', async () => {
    let failed = false
    vi.mocked(api).mockImplementation(async (_path, options) => {
      if (options?.method === 'POST') {
        failed = true
        return { operation: { id: 'start-eight', phase: 'running', action: 'maps.start', partition: 8 } }
      }
      const data = snapshot()
      return failed ? { ...data, metadata: { ...data.metadata, operation: { id: 'start-eight', phase: 'failed', action: 'maps.start', partition: 8, error: 'Memory is unavailable.' } } } : data
    })
    render(<DockerMapManagement />)
    fireEvent.click(await screen.findByRole('button', { name: 'Start and keep running' }))
    await screen.findByText('Change not applied. Memory is unavailable.')
    expect(screen.queryByText(/start in progress/)).toBeNull()
    expect(screen.queryByText(/start completed/)).toBeNull()
  })
  it('sorts names both ways and keeps the editor with its map', async () => {
    vi.mocked(api).mockResolvedValue(snapshot())
    render(<DockerMapManagement />)
    fireEvent.click((await screen.findAllByRole('button', { name: 'Edit resources' }))[0])
    fireEvent.change(screen.getByLabelText('Hagga Basin RAM limit in GiB'), { target: { value: '12' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sort by Map', exact: true }))
    const names = () => Array.from(document.querySelectorAll('tbody tr > td:first-child > strong')).map(node => node.textContent)
    expect(names()).toEqual(['Deep Desert', 'Hagga Basin'])
    expect(screen.getByRole('columnheader', { name: /Map/ })).toHaveAttribute('aria-sort', 'ascending')
    expect(screen.getByLabelText('Hagga Basin RAM limit in GiB')).toHaveValue(12)
    expect(screen.getByRole('region', { name: 'Hagga Basin resources' }).closest('tr')?.previousElementSibling).toHaveTextContent('Hagga Basin')
    fireEvent.click(screen.getByRole('button', { name: 'Sort by Map', exact: true }))
    expect(names()).toEqual(['Hagga Basin', 'Deep Desert'])
    fireEvent.change(screen.getByPlaceholderText('Map name'), { target: { value: 'desert' } })
    expect(names()).toEqual(['Deep Desert'])
  })
  it('sorts RAM, swap and players numerically, keeping unknown samples last', async () => {
    const base = snapshot()
    const data = { ...base, metadata: { ...base.metadata, plan: { ...base.metadata.plan, maps: [...base.metadata.plan.maps, { map: 'Overmap', partitions: [2], memoryBytes: 2 * 1024 ** 3, initialReplicas: 1 }] }, services: [
      { component: 'game-1', state: 'running', gameReady: true, players: 12 },
      { component: 'game-8', state: 'running', gameReady: true, players: 2 },
      { component: 'game-2', state: 'running', gameReady: false },
    ] }, samples: { containers: [
      { component: 'game-1', memory: { usedBytes: 12 * 1024 ** 3, limitBytes: 16 * 1024 ** 3, swapUsedBytes: 12 * 1024 ** 3 } },
      { component: 'game-8', memory: { usedBytes: 2 * 1024 ** 3, limitBytes: 16 * 1024 ** 3, swapUsedBytes: 2 * 1024 ** 3 } },
    ] } }
    vi.mocked(api).mockResolvedValue(data)
    render(<DockerMapManagement />)
    await screen.findByText('Overmap', { exact: true, selector: 'strong' })
    const names = () => Array.from(document.querySelectorAll('tbody tr > td:first-child > strong')).map(node => node.textContent)
    for (const key of ['RAM', 'Swap', 'Players']) {
      fireEvent.click(screen.getByRole('button', { name: `Sort by ${key}`, exact: true }))
      expect(names()).toEqual(['Deep Desert', 'Hagga Basin', 'Overmap'])
      fireEvent.click(screen.getByRole('button', { name: `Sort by ${key}`, exact: true }))
      expect(names()).toEqual(['Hagga Basin', 'Deep Desert', 'Overmap'])
    }
    fireEvent.click(screen.getByRole('button', { name: 'Sort by Status', exact: true }))
    expect(names()[0]).toBe('Overmap')
    fireEvent.click(screen.getByRole('button', { name: 'Sort by Mode', exact: true }))
    expect(names()[0]).toBe('Hagga Basin')
  })
  it('shows the target restarting before its old ready process has stopped', async () => {
    vi.mocked(api).mockResolvedValue({...snapshot(),metadata:{...snapshot().metadata,operation:{action:'maps.restart',partition:1,phase:'running'}}})
    render(<DockerMapManagement />)
    expect(await screen.findByText('Restarting',{exact:true})).toBeInTheDocument()
  })
  it('opens resources immediately below the selected row without game settings', async () => {
    const s=snapshot()
    s.metadata.plan.maps.push({map:'Overmap',partitions:[2],memoryBytes:2*1024**3,initialReplicas:1})
    vi.mocked(api).mockResolvedValue(s)
    render(<DockerMapManagement />)
    fireEvent.click((await screen.findAllByRole('button',{name:'Edit resources'}))[2])
    const editor=screen.getByRole('region',{name:'Overmap resources'})
    expect(editor.closest('tr')?.previousElementSibling).toHaveTextContent('Overmap')
    expect(screen.getByLabelText('Overmap RAM limit in GiB')).toBeInTheDocument()
    expect(screen.queryByRole('button',{name:'Global defaults',exact:true})).toBeNull()
    expect(screen.queryByText('Editing partition 2')).toBeNull()
  })
  it('keeps RAM errors beside Save RAM and preserves drafts when switching maps', async () => {
    vi.mocked(api).mockImplementation(async (_path, options) => { if (options?.method === 'PUT') throw new Error('Docker could not apply this limit.'); return snapshot() as never })
    render(<DockerMapManagement />)
    fireEvent.click((await screen.findAllByRole('button',{name:'Edit resources'}))[0])
    fireEvent.change(screen.getByLabelText('Hagga Basin RAM limit in GiB'),{target:{value:'12'}})
    fireEvent.click(screen.getByRole('button',{name:'Save RAM'}))
    const error=await screen.findByRole('alert')
    expect(error).toHaveTextContent('Change not applied.')
    expect(error.closest('section')).toHaveAttribute('aria-label','Hagga Basin resources')
    fireEvent.click(screen.getAllByRole('button',{name:'Edit resources'})[1])
    fireEvent.click(screen.getAllByRole('button',{name:'Edit resources'})[0])
    expect(screen.getByLabelText('Hagga Basin RAM limit in GiB')).toHaveValue(12)
    expect(screen.getByRole('alert')).toHaveTextContent('Docker could not apply this limit.')
  })
  it('keeps an action failure visible after a successful observation refresh', async () => {
    vi.mocked(api).mockImplementation(async (_path, options) => { if (options?.method === 'PUT') throw new Error('Mode could not be saved.'); return snapshot() as never })
    render(<DockerMapManagement />)
    fireEvent.change(await screen.findByLabelText('Deep Desert mode'), { target: { value: 'always-on' } })
    await screen.findByText(/Mode could not be saved./)
    await waitFor(() => expect(screen.queryByText('Applying…')).toBeNull())
    const observations=vi.mocked(api).mock.calls.filter(([,options])=>!options?.method).length
    fireEvent.click(screen.getByRole('button', { name: 'Refresh', exact: true }))
    await waitFor(() => expect(vi.mocked(api).mock.calls.filter(([, options]) => !options?.method).length).toBeGreaterThan(observations))
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
    fireEvent.click(screen.getAllByRole('button', { name: 'Edit resources' })[1])
    expect(screen.getByRole('region',{name:'Deep Desert resources'})).toBeInTheDocument()
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
