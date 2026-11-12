import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { api, withOnlinePlayerGuard } from '../../api/client'
import { mapLabel } from '../../util/mapLabel'
import { MemoryBalancingControl } from '../../components/MemoryBalancingControl'
import { Link } from '../../router'

type Service = { component: string; state: string; gameReady?: boolean; players?: number; startedAt?: number; desiredState?: string; exitCode?: number }
type MapRow = { map: string; partitions: number[]; memoryBytes: number; initialReplicas: number }
type Sample = { component?: string; memory?: { usedBytes: number; limitBytes: number; swapUsedBytes?: number | null } | null }
type Management = {
  metadata: { desiredState: string; operation?: { id?: string; phase: string; error?: string; action?: string; partition?: number }; pendingMemoryChange?: { map: string; bytes: number }; plan: { maps: MapRow[]; games: { map: string; partition: number }[] } | null; services: Service[] }
  resources: { host: { memoryBytes: number; availableBytes: number; swapTotalBytes?: number; swapFreeBytes?: number }; observedAt?: number; memoryGiB: number; reservedMemoryGiB: number; serviceReserveGiB: number }
  modes: Record<string, string>; modeError?: string; samplesFresh: boolean; samples: { observedAt?: number; containers: Sample[] }
  swapPolicy?: { enabled: boolean; perServerGiB?: number }
  memoryBalancingEnabled?: boolean
  pendingMapMode?: { map: string; mode: string }
}
const GIB = 1024 ** 3
const gb = (bytes: number) => `${(bytes / GIB).toFixed(1)} GiB`
const modeNames: Record<string, string> = { core: 'Core map', dynamic: 'On demand', 'always-on': 'Keep running', 'overmap-active': 'Follow Overmap', disabled: 'No new starts' }
type SortKey = 'map' | 'status' | 'players' | 'mode' | 'ram' | 'swap'
const modeHelp: Record<string, string> = {
  core: 'Required by the world. Core maps keep their normal startup policy.',
  dynamic: 'Opens for player travel. Once empty, the map can shut down when memory balancing is enabled.',
  'always-on': 'Leaves this map running between visits, reserving memory even when no players are there.',
  'overmap-active': 'Runs this map while Overmap has players. After Overmap has been empty for one minute, this map returns to its normal shutdown policy once its own players have left.',
  disabled: 'Prevents this map from starting for new travel requests. If it is already running, it stays running until stopped normally.',
}
function savedSelection(key: string) {
  try { return sessionStorage.getItem(`dst.docker.maps.${key}`) ?? '' } catch { return '' }
}
function savedRamDrafts(): Record<string, string> {
  try {
    const value = JSON.parse(savedSelection('ram') || '{}')
    return value && typeof value === 'object' && !Array.isArray(value) && Object.values(value).every(item => typeof item === 'string') ? value : {}
  } catch { return {} }
}

export function DockerMapManagement({ legacyTools }: { legacyTools?: ReactNode }) {
  const [data, setData] = useState<Management | null>(null)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState(() => savedSelection('query'))
  const [editing, setEditing] = useState(() => /^\d+$/.test(savedSelection('editing')) ? savedSelection('editing') : '')
  const [feedbackAt, setFeedbackAt] = useState('')
  const [controlRequest, setControlRequest] = useState<{ id: string; name: string; action: string } | null>(null)
  const [memory, setMemory] = useState<Record<string, string>>(savedRamDrafts)
  const [receivedAt, setReceivedAt] = useState(0)
  const [clock, setClock] = useState(Date.now())
  const [more, setMore] = useState(false)
  const [sort, setSort] = useState<{ key: SortKey; descending: boolean } | null>(null)
  const mounted = useRef(true)
  const loading = useRef(false)
  useEffect(() => {
    try { sessionStorage.setItem('dst.docker.maps.query', query); sessionStorage.setItem('dst.docker.maps.editing', editing) } catch { /* Storage may be disabled. */ }
  }, [query, editing])
  useEffect(() => { try { sessionStorage.setItem('dst.docker.maps.ram', JSON.stringify(memory)) } catch { /* Storage may be disabled. */ } }, [memory])
  const load = async () => {
    if (loading.current) return
    loading.current = true
    try { const next = await api<Management>('/api/docker/maps'); if (mounted.current) { setData(next); setReceivedAt(Date.now()); setClock(Date.now()); setLoadError('') } }
    catch (e) { if (mounted.current) setLoadError(e instanceof Error ? e.message : String(e)) }
    finally { loading.current = false }
  }
  useEffect(() => {
    mounted.current = true; void load()
    const timer = window.setInterval(() => { setClock(Date.now()); if (!document.hidden) void load() }, 10_000)
    return () => { mounted.current = false; window.clearInterval(timer) }
  }, [])
  const update = async (body: Record<string, unknown>, success: string) => {
    setBusy(true); setMessage(''); setError(''); setFeedbackAt(`${body.map}:${body.setting}`)
    try { await api('/api/docker/maps', { method: 'PUT', body: JSON.stringify(body) }); setMessage(success); await load(); return true }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); await load(); return false }
    finally { setBusy(false) }
  }
  const control = async (target: string, name: string, operation: 'start' | 'stop' | 'restart') => {
    setBusy(true); setMessage(''); setError(''); setFeedbackAt(`${name}:control`)
    try {
      const result = await withOnlinePlayerGuard(force => api<Management['metadata']>(`/api/docker/maps${force ? '?force=true' : ''}`, { method: 'POST', body: JSON.stringify({ target, action: operation }) }))
      if (result.operation?.id) setControlRequest({ id: result.operation.id, name, action: operation })
      setMessage(`${mapLabel(name)}: ${operation} in progress…`)
      await load()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  useEffect(() => {
    if (!controlRequest || !data?.metadata.operation || data.metadata.operation.id !== controlRequest.id) return
    const operation = data.metadata.operation
    if (operation.phase === 'failed' || operation.phase === 'interrupted') {
      setMessage(''); setError(operation.error || `${mapLabel(controlRequest.name)}: ${controlRequest.action} did not complete.`)
      setControlRequest(null)
    } else if (operation.phase === 'completed') {
      setMessage(`${mapLabel(controlRequest.name)}: ${controlRequest.action} completed.`); setControlRequest(null)
    }
  }, [controlRequest, data?.metadata.operation])
  const maps = data?.metadata.plan?.maps ?? []
  const services = data?.metadata.services ?? []
  const fresh = !!data?.samplesFresh && clock - (data.samples.observedAt ? data.samples.observedAt * 1000 : receivedAt) < 30_000
  const hostFresh = clock - receivedAt < 30_000
  const sample = (component: string) => {
    const memory = fresh ? data?.samples.containers.find(row => row.component === component)?.memory : null
    return memory && Number.isFinite(memory.usedBytes) && memory.usedBytes >= 0 ? memory : undefined
  }
  const working = services.filter(service => service.component.startsWith('game-') && service.state === 'running').map(service => sample(service.component)?.usedBytes)
  const measured = working.filter((value): value is number => value !== undefined)
  const worldRunning = data?.metadata.desiredState === 'running'
  const operationRunning = data?.metadata.operation?.phase === 'running'
  const pendingMemory = data?.metadata.pendingMemoryChange
  const operationBusy = operationRunning || !!pendingMemory
  const rowStatus = (row: MapRow) => {
    const rows = row.partitions.map(partition => services.find(service => service.component === `game-${partition}`))
    const running = rows.filter(service => service?.state === 'running').length
    const ready = rows.filter(service => service?.state === 'running' && service.gameReady === true).length
    const loadingMap = rows.some(service => service?.state === 'restarting' || service?.desiredState === 'running' && service?.gameReady !== true)
    const expected = rows.filter(service => service?.desiredState === 'running' || service?.state === 'running' || service?.state === 'restarting').length
    const failed = !operationBusy && rows.some(service => service?.state === 'exited' && service.desiredState === 'running')
    const restarting = data?.metadata.operation?.action === 'maps.restart' && data.metadata.operation.phase === 'running' && row.partitions.includes(data.metadata.operation.partition ?? -1)
    return !worldRunning && (running > 0 || loadingMap) ? 'Stopping' : restarting ? 'Restarting' : failed ? 'Needs attention' : ready >= expected && ready > 0 ? 'Ready' : running > 0 || loadingMap ? 'Loading' : 'Not running'
  }
  const sortValue = (row: MapRow, key: SortKey): string | number | null => {
    if (key === 'map') return mapLabel(row.map)
    if (key === 'mode') return modeNames[data?.modes[row.map] ?? 'dynamic'] ?? ''
    if (key === 'status') return rowStatus(row)
    const running = row.partitions.filter(partition => services.some(service => service.component === `game-${partition}` && service.state === 'running'))
    if (!running.length) return 0
    const values = running.map(partition => key === 'players' ? services.find(service => service.component === `game-${partition}`)?.players : key === 'ram' ? sample(`game-${partition}`)?.usedBytes : sample(`game-${partition}`)?.swapUsedBytes)
    return values.every(value => value != null && Number.isFinite(value)) ? values.reduce<number>((sum, value) => sum + (value ?? 0), 0) : null
  }
  const visibleMaps = maps.filter(row => `${row.map} ${mapLabel(row.map)} ${row.partitions.join(' ')}`.toLowerCase().includes(query.toLowerCase()))
  if (sort) {
    const values = new Map(visibleMaps.map(row => [row.map, sortValue(row, sort.key)]))
    visibleMaps.sort((a, b) => {
      const left = values.get(a.map) ?? null, right = values.get(b.map) ?? null
      // Unknown samples stay last in either direction; they are never treated as zero.
      if (left === null || right === null) return left === right ? 0 : left === null ? 1 : -1
      const order = typeof left === 'number' && typeof right === 'number' ? left - right : String(left).localeCompare(String(right), undefined, { numeric: true })
      return (sort.descending ? -order : order) || mapLabel(a.map).localeCompare(mapLabel(b.map), undefined, { numeric: true })
    })
  }
  const sortButton = (key: SortKey, label: string) => <button type="button" className="inline-flex items-center gap-1 rounded focus-visible:outline-2 focus-visible:outline-accent" aria-label={`Sort by ${label}`} onClick={() => setSort(previous => ({ key, descending: previous?.key === key ? !previous.descending : false }))}>{label}<span aria-hidden="true">{sort?.key === key ? sort.descending ? '↓' : '↑' : '↕'}</span></button>
  const sortDirection = (...keys: SortKey[]) => sort && keys.includes(sort.key) ? sort.descending ? 'descending' as const : 'ascending' as const : undefined
  const selectedMap = maps.find(row => row.partitions.some(partition => String(partition) === editing))
  const ramDraft = selectedMap ? memory[selectedMap.map] ?? String(selectedMap.memoryBytes / GIB) : ''
  const ramDirty = !!selectedMap && (ramDraft === '' || Number(ramDraft) !== selectedMap.memoryBytes / GIB)
  const dirty = ramDirty
  const selectedRestarting = data?.metadata.operation?.action === 'maps.restart' && data.metadata.operation.phase === 'running' && String(data.metadata.operation.partition) === editing
  const selectedService = services.find(service => service.component === `game-${editing}`)
  const sampleAge = Math.max(0, Math.floor((clock - (data?.samples.observedAt ? data.samples.observedAt * 1000 : receivedAt)) / 1000))
  const feedback = (target: string) => feedbackAt === target && (busy || error || message) ? <p role={error ? 'alert' : 'status'} className={`mt-2 text-sm ${error ? 'text-danger' : busy || controlRequest ? 'text-text-muted' : 'text-success'}`}>{busy ? 'Applying…' : error ? `${pendingMemory ? 'Change incomplete.' : 'Change not applied.'} ${error}` : message}</p> : null
  const resourceEditor = selectedMap && <section id={`resources-${selectedMap.map}`} aria-label={`${mapLabel(selectedMap.map)} resources`} className="space-y-3">
    <div className="flex flex-wrap items-end gap-3">
      <label className="text-sm">RAM limit per partition<div className="mt-1 flex items-center gap-2"><input className="map-management-input w-24" type="number" min="0.25" max="128" step="0.25" aria-label={`${mapLabel(selectedMap.map)} RAM limit in GiB`} value={ramDraft} disabled={busy || operationBusy} onChange={event => setMemory(previous => ({ ...previous, [selectedMap.map]: event.target.value }))} /> GiB</div></label>
      <button className="btn-primary" disabled={!ramDirty || busy || operationBusy || !Number.isFinite(Number(ramDraft)) || Number(ramDraft) < 0.25 || Number(ramDraft) > 128 || Number(ramDraft) * 4 % 1 !== 0} onClick={async () => { if (await update({ setting: 'memory', map: selectedMap.map, memoryGiB: Number(ramDraft) }, 'RAM limit applied.')) setMemory(previous => { const next = { ...previous }; delete next[selectedMap.map]; return next }) }}>Save RAM</button>
      {ramDirty && <button className="btn-secondary" disabled={busy} onClick={() => setMemory(previous => { const next = { ...previous }; delete next[selectedMap.map]; return next })}>Discard RAM change</button>}
    </div>
    {feedback(`${selectedMap.map}:memory`)}
    {pendingMemory?.map === selectedMap.map && <div className="flex flex-wrap items-center gap-2 text-sm text-warning"><span>RAM change incomplete.</span><button className="btn-secondary" disabled={busy || operationRunning} onClick={() => void update({ setting: 'memory', map: pendingMemory.map, memoryGiB: pendingMemory.bytes / GIB }, 'RAM limit applied.')}>Retry RAM allocation</button></div>}

    <p className="text-xs text-text-muted">RAM changes apply while the map is running.</p>
    <div className={`flex flex-wrap items-center gap-2 ${selectedMap.partitions.length === 1 ? 'md:hidden' : ''}`}>
      {selectedMap.partitions.length > 1 ? <label className="text-sm">Partition<select className="map-management-input ml-2" aria-label={`${mapLabel(selectedMap.map)} partition`} value={editing} onChange={event => setEditing(event.target.value)}>{selectedMap.partitions.map(partition => <option key={partition}>{partition}</option>)}</select></label> : <span className="text-sm">Partition {editing}</span>}
      <span className="text-sm text-text-muted">{selectedRestarting ? 'Restarting' : selectedService?.gameReady ? 'Ready' : selectedService?.state ?? 'Not running'}</span>
      {selectedService?.state === 'running' ? <><button className="btn-secondary" disabled={busy || operationBusy || dirty} onClick={() => void control(editing, selectedMap.map, 'restart')}>Restart partition {editing}</button>{data?.modes[selectedMap.map] !== 'core' && <button className="btn-secondary" disabled={busy || operationBusy || dirty} onClick={() => void control(editing, selectedMap.map, 'stop')}>Stop partition {editing}</button>}</> : <button className="btn-secondary" disabled={busy || operationBusy || dirty || !worldRunning || data?.modes[selectedMap.map] === 'disabled'} onClick={() => void control(editing, selectedMap.map, 'start')}>Start partition {editing}</button>}
    </div>
    {feedback(`${selectedMap.map}:control`)}
  </section>
  return <div className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-xl font-semibold">Maps &amp; memory</h2><p className="mt-1 text-sm text-text-muted">Manage map availability and memory.</p></div><div className="flex flex-wrap gap-2"><button type="button" className="btn-secondary" onClick={() => void load()}>Refresh</button></div></div>
    {data && <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <div className="card p-4"><p className="text-xs text-text-muted">Host RAM</p><strong className="text-xl">{hostFresh ? `${gb(data.resources.host.memoryBytes - data.resources.host.availableBytes)} used` : 'Sample unavailable'}</strong><p className="text-xs text-text-muted">{hostFresh ? `${gb(data.resources.host.availableBytes)} available · ${gb(data.resources.host.memoryBytes)} total` : 'Refresh to read current availability'}</p></div>
      <div className="card p-4"><p className="text-xs text-text-muted">Maps using RAM</p><strong className="text-xl">{measured.length ? `${measured.length < working.length ? 'At least ' : ''}${gb(measured.reduce((sum, value) => sum + value, 0))}` : working.length ? 'Awaiting sample' : 'No maps running'}</strong><p className="text-xs text-text-muted">{measured.length} of {working.length} running maps measured</p></div>
      <div className="card p-4"><p className="text-xs text-text-muted">Host swap</p><strong className="text-xl">{hostFresh && data.resources.host.swapTotalBytes != null && data.resources.host.swapFreeBytes != null ? `${gb(Math.max(0, data.resources.host.swapTotalBytes - data.resources.host.swapFreeBytes))} used` : 'Usage unavailable'}</strong><p className="text-xs text-text-muted">{hostFresh && data.resources.host.swapFreeBytes != null ? `${gb(data.resources.host.swapFreeBytes)} available · shared by the host` : 'Swap allowance is separate from consumption'}</p></div>
      <div className="card p-4"><p className="text-xs text-text-muted">Map ceilings / server budget</p><strong className="text-xl">{data.resources.reservedMemoryGiB.toFixed(1)} / {data.resources.memoryGiB} GiB</strong><p className="text-xs text-text-muted">Running limits + {data.resources.serviceReserveGiB} GiB service reserve · <Link to="/settings" className="text-accent">Host allocation</Link></p></div>
    </div>}
    {data && <p className="text-xs text-text-muted" role="status">{fresh ? `Map samples updated ${sampleAge}s ago` : 'Map samples unavailable or stale'} · {data.memoryBalancingEnabled === false ? 'Classic map policy' : 'Empty dynamic maps can unload'} · {data.swapPolicy?.enabled ? `Swap policy: up to ${data.swapPolicy.perServerGiB} GiB per map` : 'Swap policy: Docker default allowance'}</p>}
    <details className="card p-4"><summary className="cursor-pointer font-semibold">Memory &amp; startup policy</summary><MemoryBalancingControl /><div className="mt-4 border-t border-border pt-3 text-sm"><strong>After a host restart</strong><p className="mt-1 text-text-muted">DST resumes maps saved as running. A stopped battlegroup stays stopped. Maps may load together. Startup checks their limits and keeps 2 GiB host headroom; the server budget also keeps {data?.resources.serviceReserveGiB ?? 2} GiB for supporting services.</p><p className="mt-2 text-text-muted">On demand follows player travel. Keep running maintains a warm map. Follow Overmap releases its warm setting after Overmap has been empty for one minute and this map has no players. Unknown occupancy does not qualify as empty.</p></div></details>
    <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-sm">Choose when maps run</summary><div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{Object.keys(modeNames).filter(mode => mode !== 'core').map(mode => <div key={mode} className="rounded-lg border border-border p-3"><strong>{modeNames[mode]}</strong><p className="mt-1 text-sm text-text-muted">{modeHelp[mode]}</p></div>)}</div></details>
    <label className="block text-sm">Find a map<input className="map-management-input mt-1 w-full sm:max-w-md" type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Map name" /></label>
    {loadError && <p role="alert" className="rounded-lg border border-danger/40 p-3 text-danger">{loadError}</p>}
    {pendingMemory && selectedMap?.map !== pendingMemory.map && <div className="flex flex-wrap items-center gap-3 rounded-lg border border-warning/40 p-3"><p>RAM allocation needs recovery: {mapLabel(pendingMemory.map)} → {gb(pendingMemory.bytes)} per partition. Some partitions may already have this limit.</p><button className="btn-secondary" disabled={busy || operationRunning} onClick={() => void update({ setting: 'memory', map: pendingMemory.map, memoryGiB: pendingMemory.bytes / GIB }, `${mapLabel(pendingMemory.map)} RAM allocation completed.`)}>Retry RAM allocation</button></div>}
    {data?.metadata.operation?.error && !operationBusy && <p role="alert" className="rounded-lg border border-danger/40 p-3 text-danger">Last server operation: {data.metadata.operation.error}</p>}
    {data?.modeError && <p role="alert" className="text-warning">{data.modeError}</p>}
    {data?.pendingMapMode && <div className="flex flex-wrap items-center gap-3 rounded-lg border border-warning/40 p-3"><p>Map mode change pending: {mapLabel(data.pendingMapMode.map)} → {modeNames[data.pendingMapMode.mode]}.</p><button className="btn-secondary" disabled={busy || operationBusy} onClick={() => void update({ setting: 'mode', map: data.pendingMapMode!.map, mode: data.pendingMapMode!.mode }, 'Pending map mode reconciled.')}>Retry map mode</button></div>}
    {data && !fresh && <p className="text-sm text-warning">Memory samples are unavailable or older than 30 seconds. Usage is shown as unknown until a fresh sample arrives.</p>}
    {operationRunning && <p role="status">A server operation is in progress. Map controls unlock when it completes.</p>}
    {!data && !loadError && <p role="status">Loading maps and memory…</p>}
    {data && !maps.length && <p>Complete Server Setup to prepare the map catalogue.</p>}
    {data && maps.length > 0 && !maps.some(row => `${row.map} ${mapLabel(row.map)} ${row.partitions.join(' ')}`.toLowerCase().includes(query.toLowerCase())) && <p>No maps match this search.</p>}
    <div id="docker-map-list" className="scroll-mt-20 overflow-x-auto rounded-lg border border-border"><table className="w-full text-left text-sm"><thead className="bg-surface text-text-muted"><tr><th className="p-3" aria-sort={sortDirection('map')}>{sortButton('map', 'Map')}</th><th className="p-3" aria-sort={sortDirection('status', 'players')}>{sortButton('status', 'Status')} / {sortButton('players', 'Players')}</th><th className="hidden p-3 md:table-cell" aria-sort={sortDirection('mode')}>{sortButton('mode', 'Mode')}</th><th className="hidden p-3 md:table-cell" aria-sort={sortDirection('ram', 'swap')}>{sortButton('ram', 'RAM')} / {sortButton('swap', 'Swap')}</th><th className="hidden p-3 md:table-cell">Actions</th></tr></thead><tbody>{visibleMaps.map(row => {
      const rows = row.partitions.map(partition => services.find(service => service.component === `game-${partition}`))
      const running = rows.filter(service => service?.state === 'running').length
      const ready = rows.filter(service => service?.state === 'running' && service.gameReady === true).length
      const expected = rows.filter(service => service?.desiredState === 'running' || service?.state === 'running' || service?.state === 'restarting').length
      const failed = !operationBusy && rows.some(service => service?.state === 'exited' && service.desiredState === 'running')
      const status = rowStatus(row)
      const mode = data?.modes[row.map] ?? 'dynamic'
      const usage = row.partitions.map(partition => sample(`game-${partition}`))
      const used = usage.filter(value => value !== undefined)
      const totalUsed = used.reduce((sum, value) => sum + (value?.usedBytes ?? 0), 0)
      const target = String(row.partitions[0])
      const editorOpen = row.partitions.some(partition => String(partition) === editing)
      const players = rows.filter(service => service?.state === 'running').map(service => service?.players)
      return <Fragment key={row.map}><tr className="border-t border-border align-top">
        <td className="p-3"><strong>{mapLabel(row.map)}</strong><p className="mt-1 text-xs text-text-muted">Partition{row.partitions.length === 1 ? '' : 's'} {row.partitions.join(', ')}</p><details className="mt-1 text-xs text-text-muted"><summary className="cursor-pointer">Map identifier</summary><span className="font-mono">{row.map}</span></details><p className="mt-2 text-xs text-text-muted md:hidden">{modeNames[mode]} · {used.length ? `${gb(totalUsed)} used` : running ? 'Usage unknown' : 'Not running'}<br />{gb(row.memoryBytes)} limit per partition</p><div className="mt-2"><button className={editorOpen ? 'btn-primary' : 'btn-secondary'} aria-expanded={editorOpen} aria-controls={`resources-${row.map}`} onClick={() => setEditing(editorOpen ? '' : target)}>Edit resources</button></div></td>
        <td className="p-3"><span className={status === 'Ready' ? 'text-success' : status === 'Needs attention' ? 'text-danger' : ['Loading', 'Restarting', 'Stopping'].includes(status) ? 'text-warning' : 'text-text-muted'}>{status}</span>{running > 0 && <><p className="mt-1 text-xs">{ready} of {Math.max(running,expected)} ready</p><p className="mt-1 text-xs text-text-muted">{players.every(value => value != null) ? `${players.reduce((sum, value) => sum + (value ?? 0), 0)} players` : 'Players unknown'}</p></>}{failed && <p className="mt-1 text-xs text-text-muted">A map process exited while requested to run. Check its logs.</p>}</td>
        <td className="hidden min-w-44 p-3 md:table-cell" title={modeHelp[mode]}>{mode === 'core' ? <><strong>Core map</strong><p className="mt-1 text-xs text-text-muted">Required by this world</p></> : <select aria-label={`${mapLabel(row.map)} mode`} className="map-management-input w-full" value={mode} disabled={busy || operationBusy} onChange={event => void update({ setting: 'mode', map: row.map, mode: event.target.value }, `${mapLabel(row.map)} mode saved.`)}>{Object.entries(modeNames).filter(([key]) => key !== 'core').map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select>}{feedback(`${row.map}:mode`)}</td>
        <td className="hidden min-w-60 p-3 md:table-cell">{running > 0 ? <><p>{used.length ? `${used.length === running ? '' : 'At least '}${gb(totalUsed)} used` : 'Usage unknown'} / {gb(row.memoryBytes * running)} {running > 1 ? 'combined limit' : 'limit per map'}</p><div className="my-2 h-2 overflow-hidden rounded bg-border" aria-hidden="true"><div className="h-full bg-accent" style={{ width: `${Math.min(100, totalUsed / (row.memoryBytes * Math.max(1, running)) * 100)}%` }} /></div><p className="text-xs text-text-muted">Swap used: {used.length === running && used.every(value => value?.swapUsedBytes != null) ? gb(used.reduce((sum, value) => sum + (value?.swapUsedBytes ?? 0), 0)) : 'not reported by Docker'}</p><p className="mt-1 text-xs text-text-muted">Swap allowance per map: {data?.swapPolicy?.enabled ? `${data.swapPolicy.perServerGiB} GiB` : `${gb(row.memoryBytes)} (Docker default)`}</p></> : <p className="text-text-muted">Unallocated · saved limit {gb(row.memoryBytes)}</p>}
        </td>
        <td className="hidden p-3 md:table-cell"><div className="flex max-w-64 flex-wrap gap-2">{row.partitions.length > 1 ? <span className="text-xs text-text-muted">Choose a partition in Edit resources.</span> : running ? <><button className="btn-secondary" disabled={busy || operationBusy || dirty} onClick={() => void control(target, row.map, 'restart')}>Restart</button>{mode !== 'core' && <button className="btn-secondary" disabled={busy || operationBusy || dirty} onClick={() => void control(target, row.map, 'stop')}>Stop</button>}</> : <button className="btn-secondary" title={!worldRunning ? 'Start the battlegroup first' : mode === 'disabled' ? 'Change No new starts mode before starting this map' : 'Starts this partition and leaves it running'} disabled={busy || operationBusy || dirty || !worldRunning || mode === 'disabled'} onClick={() => void control(target, row.map, 'start')}>Start and keep running</button>}</div>{!editorOpen && feedback(`${row.map}:control`)}</td>
      </tr>{editorOpen && <tr className="border-t border-border"><td colSpan={5} className="bg-surface p-3">{resourceEditor}</td></tr>}</Fragment>
    })}</tbody></table></div>

    <p className="text-xs text-text-muted">Memory figures use fresh Docker samples and exclude reclaimable file cache. A saved limit is a ceiling, not RAM already consumed. Swap is emergency disk-backed memory; it does not enlarge the physical RAM budget.</p>
    {legacyTools && <div><button type="button" className="btn-secondary" onClick={() => setMore(value => !value)}>{more ? 'Hide additional map tools' : 'Additional map tools'}</button>{more && <div className="mt-3">{legacyTools}</div>}</div>}
  </div>
}
