import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { api } from '../src/api/client'
import { PerMapSettings } from '../src/pages/gameconfig/PerMapSettings'

vi.mock('../src/api/client', () => ({ api: vi.fn(), withOnlinePlayerGuard: (fn: (force: boolean) => unknown) => fn(false) }))
const targets = [{ id: '1', map: 'Survival_1', label: 'Hagga Basin · Sietch Abbir (1)' }, { id: '8', map: 'DeepDesert_1', label: 'Deep Desert · partition 8' }]
const snapshot = (target = '1', file = 'server') => ({ targets, target, file, revision: 'a'.repeat(64), raw: '', adapterReady: true, overridden: false, pendingRestart: false,
  fields: [{ id: 'GatheringAmount', key: 'GatheringAmount', label: 'Gathering Amount', group: 'World and economy', type: 'float', value: '1', editable: true }] })
afterEach(() => { cleanup(); sessionStorage.clear(); vi.clearAllMocks() })
function setup() {
  vi.mocked(api).mockImplementation(async (path, options) => {
    const url = new URL(String(path), 'http://local')
    if (options?.method === 'PUT') { const body = JSON.parse(String(options.body)); return { ...snapshot(body.target, body.file), overridden: true, pendingRestart: true, fields: [{ ...snapshot().fields[0], value: body.updates.GatheringAmount }] } as never }
    const target = url.searchParams.get('target')
    return (target ? snapshot(target, url.searchParams.get('file') ?? 'server') : { targets }) as never
  })
}
describe('Per-map settings', () => {
  it('shows a failed restart without leaving the duplicate-request guard stuck', async () => {
    vi.mocked(api).mockImplementation(async path => String(path)==='/api/docker/maps'
      ? {metadata:{operation:{action:'maps.restart',partition:8,phase:'failed',error:'Map stop failed'},services:[{component:'game-8',state:'running',gameReady:false}]}} as never
      : {...snapshot('8'),pendingRestart:true,running:true} as never)
    render(<PerMapSettings initialTarget="8" />)
    await screen.findByText('Restart failed',{exact:true})
    expect(screen.getByRole('button',{name:'Restart this map'})).toBeEnabled()
    expect(screen.getByText(/Map stop failed/)).toBeInTheDocument()
  })
  it('follows a recorded restart through loading to ready and clears applied pending state', async () => {
    vi.useFakeTimers()
    let phase=0
    vi.mocked(api).mockImplementation(async path => {
      if(String(path)==='/api/docker/maps')return {metadata:{operation:{action:'maps.restart',partition:8,phase:phase===0?'running':'completed'},services:[{component:'game-8',state:'running',gameReady:phase===2}]}} as never
      return {...snapshot('8'),pendingRestart:phase!==2,running:true} as never
    })
    try {
      await act(async()=>{render(<PerMapSettings initialTarget="8" />)})
      expect(screen.getByText('Restarting',{exact:true})).toBeInTheDocument()
      expect(screen.getByRole('button',{name:/Restart in progress/})).toBeDisabled()
      phase=1;await act(async()=>{await vi.advanceTimersByTimeAsync(4000)})
      expect(screen.getByText('Loading',{exact:true})).toBeInTheDocument()
      phase=2;await act(async()=>{await vi.advanceTimersByTimeAsync(4000)})
      expect(screen.getByText('Ready',{exact:true})).toBeInTheDocument()
      expect(screen.queryByText('Pending restart',{exact:true})).toBeNull()
    } finally { vi.useRealTimers() }
  })
  it('opens Global defaults in the same editor and saves the global target', async () => {
    setup(); render(<PerMapSettings />)
    const input = await screen.findByLabelText('Gathering Amount')
    expect(screen.getByLabelText('Settings scope')).toHaveValue('global')
    expect(screen.queryByRole('button', { name: 'Use global settings' })).toBeNull()
    fireEvent.change(input, { target: { value: '1.5' } })
    fireEvent.click(screen.getByRole('button', { name: /Save global defaults/ }))
    await screen.findByText(/saved as Global defaults/)
    const writes=vi.mocked(api).mock.calls.filter(([,options])=>options?.method==='PUT')
    expect(JSON.parse(String(writes[0][1]?.body))).toMatchObject({target:'global',updates:{GatheringAmount:'1.5'},inherit:false})
  })
  it('uses sliders and consumes wheel steps without losing decimal precision', async () => {
    setup(); render(<PerMapSettings initialTarget="8" />)
    const input=await screen.findByLabelText('Gathering Amount')
    expect(screen.getByRole('slider')).toHaveAttribute('step','0.1')
    await act(async () => {})
    expect(fireEvent.wheel(input,{deltaY:-100})).toBe(false)
    expect(input).toHaveValue(1.1)
    fireEvent.wheel(input,{deltaY:100})
    expect(input).toHaveValue(1)
  })
  it('filters unsupported scopes even if an older catalogue includes them', async () => {
    vi.mocked(api).mockImplementation(async path => {
      const url=new URL(String(path),'http://local')
      return (url.searchParams.get('target') ? snapshot('global') : {targets:[...targets,{id:'2',map:'Overmap',label:'Overmap'},{id:'3',map:'SH_Arrakeen',label:'Arrakeen'}]}) as never
    })
    render(<PerMapSettings />)
    await screen.findByLabelText('Gathering Amount')
    expect(screen.queryByRole('option',{name:'Overmap'})).toBeNull()
    expect(screen.queryByRole('option',{name:'Arrakeen'})).toBeNull()
  })
  it('retains the chosen file, target, filter and list view across navigation', async () => {
    setup(); const first = render(<PerMapSettings initialTarget="8" />)
    await screen.findByLabelText('Gathering Amount')
    fireEvent.click(screen.getByRole('button', { name: 'Engine', exact: true }))
    await screen.findByLabelText('Gathering Amount')
    fireEvent.click(screen.getByRole('button', { name: 'List', exact: true }))
    fireEvent.change(screen.getByLabelText('Find a setting'), { target: { value: 'Gathering' } })
    first.unmount(); render(<PerMapSettings />)
    await screen.findByLabelText('Gathering Amount')
    expect(screen.getByLabelText('Settings scope')).toHaveValue('8')
    expect(screen.getByLabelText('Find a setting')).toHaveValue('Gathering')
    expect(screen.getByRole('button', { name: 'Engine', exact: true })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'List', exact: true })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Global defaults', exact: true })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Specialized editors' })).toHaveAttribute('href', '/server-settings?section=tools')
  })
  it('keeps a draft across navigation without writing or changing its target', async () => {
    setup(); const first = render(<PerMapSettings initialTarget="8" />)
    fireEvent.change(await screen.findByLabelText('Gathering Amount'), { target: { value: '3.5' } })
    first.unmount()
    render(<PerMapSettings initialTarget="8" />)
    expect(await screen.findByLabelText('Gathering Amount')).toHaveValue(3.5)
    expect(screen.getByLabelText('Settings scope')).toHaveValue('8')
    expect(vi.mocked(api).mock.calls.some(([, options]) => options?.method === 'PUT')).toBe(false)
  })
  it('retains each scope draft across navigation', async () => {
    setup(); const first = render(<PerMapSettings initialTarget="1" />)
    fireEvent.change(await screen.findByLabelText('Gathering Amount'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('Settings scope'), { target: { value: '8' } })
    await waitFor(() => expect(screen.getByLabelText('Settings scope')).toHaveValue('8'))
    first.unmount(); render(<PerMapSettings initialTarget="1" />)
    expect(await screen.findByLabelText('Gathering Amount')).toHaveValue(3)
  })
  it('does not offer a restart for a saved stopped map', async () => {
    vi.mocked(api).mockResolvedValue({ ...snapshot('8'), running: false, pendingRestart: true })
    render(<PerMapSettings initialTarget="8" />)
    await screen.findByText('Saved for next start')
    expect(screen.queryByRole('button', { name: 'Restart this map' })).not.toBeInTheDocument()
    expect(vi.mocked(api).mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false)
  })
  it('saves directly to the selected partition and keeps restart separate', async () => {
    setup(); render(<PerMapSettings initialTarget="8" />)
    fireEvent.change(await screen.findByLabelText('Gathering Amount'), { target: { value: '2.5' } })
    fireEvent.click(screen.getByRole('button', { name: /Save map settings/ }))
    await screen.findByText(/Pending restart: this map will read/)
    const writes = vi.mocked(api).mock.calls.filter(([, options]) => options?.method === 'PUT')
    expect(writes).toHaveLength(1)
    expect(JSON.parse(String(writes[0][1]?.body))).toMatchObject({ target: '8', file: 'server', inherit: false, updates: { GatheringAmount: '2.5' } })
    expect(vi.mocked(api).mock.calls.some(([path]) => String(path).includes('/restart'))).toBe(false)
  })
  it('protects an unsaved draft when switching target', async () => {
    setup(); render(<PerMapSettings initialTarget="1" />)
    fireEvent.change(await screen.findByLabelText('Gathering Amount'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('Settings scope'), { target: { value: '8' } })
    await waitFor(() => expect(screen.getByLabelText('Gathering Amount')).toHaveValue(1))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    fireEvent.change(screen.getByLabelText('Settings scope'), { target: { value: '1' } })
    await waitFor(() => expect(screen.getByLabelText('Gathering Amount')).toHaveValue(3))
    expect(screen.getByLabelText('Settings scope')).toHaveValue('1')
  })
  it('keeps the draft after a rejected stale save', async () => {
    setup(); render(<PerMapSettings initialTarget="1" />)
    fireEvent.change(await screen.findByLabelText('Gathering Amount'), { target: { value: '4' } })
    vi.mocked(api).mockRejectedValueOnce(new Error('The selected map settings changed.'))
    fireEvent.click(screen.getByRole('button', { name: /Save map settings/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('settings changed')
    expect(screen.getByRole('alert').parentElement).toHaveAttribute('aria-label','Save map settings controls')
    expect(screen.getByLabelText('Gathering Amount')).toHaveValue(4)
    expect(screen.getByRole('button', { name: /Save map settings/ })).toBeEnabled()
  })
  it('searches fields and restores a field default as an unsaved draft', async () => {
    setup(); render(<PerMapSettings initialTarget="1" />)
    await screen.findByLabelText('Gathering Amount')
    fireEvent.change(screen.getByLabelText('Find a setting'), { target: { value: 'nonexistent' } })
    expect(screen.getByText('No settings match this filter.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Find a setting'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: /Use default/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: /Save map settings/ })).toBeEnabled())
    expect(vi.mocked(api).mock.calls.every(([, options]) => options?.method !== 'PUT')).toBe(true)
  })
})
