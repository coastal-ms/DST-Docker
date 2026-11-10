import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../../api/client'
import { CollapsibleCard } from '../../components/CollapsibleCard'
import { mapLabel } from '../../util/mapLabel'

const inputClass = 'mt-1 rounded-md border border-border bg-surface px-3 py-2 text-text focus:border-accent focus:outline-none disabled:opacity-50'

type MapAllocation = { map: string; memoryGiB: number; cpus: number | null; runningInstances?: number; initialInstances?: number }
type Allocation = { memoryGiB: number; maps: MapAllocation[] }
type Resources = Allocation & {
  host: { memoryBytes: number; availableBytes: number; cpus: number }
  reservedMemoryGiB: number; reservedCpus: number; serviceReserveGiB: number
  worldRunning: boolean; configured: boolean; pending: boolean; pendingAllocation?: Allocation | null
}

export default function DockerResourcesCard() {
  const [resources, setResources] = useState<Resources | null>(null)
  const [allocation, setAllocation] = useState<Allocation | null>(null)
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [showCpuLimits, setShowCpuLimits] = useState(false)
  function receive(value: Resources) {
    setResources(value)
    setAllocation(value.pendingAllocation ?? { memoryGiB: value.memoryGiB, maps: value.maps })
    setShowCpuLimits(value.maps.some(row => row.cpus != null))
  }
  useEffect(() => {
    let active = true
    api<Resources>('/api/docker/resources').then(value => { if (active) receive(value) })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : String(e)) })
    return () => { active = false }
  }, [])
  async function save(event: FormEvent) {
    event.preventDefault()
    if (!allocation) return
    setBusy(true); setError(''); setMessage('')
    try {
      const value = await api<Resources>('/api/docker/resources', { method: 'PUT', body: JSON.stringify(allocation) })
      receive(value); setMessage('Resource allocations saved and verified. They will apply when the maps start.')
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  function updateMap(name: string, field: 'memoryGiB' | 'cpus', value: number | null) {
    setAllocation(current => current && ({ ...current, maps: current.maps.map(row => row.map === name ? { ...row, [field]: value } : row) }))
  }
  const blocked = busy || !!resources?.worldRunning
  return <CollapsibleCard id="docker-resources" title="Docker resources" icon="Cpu" subtitle="Choose the RAM available to each map.">
    {error && <p role="alert" className="text-danger mb-3">{error}</p>}
    {!allocation || !resources ? <p className="text-text-muted">{error ? 'Resource information is unavailable.' : 'Loading resources…'}</p> : <form onSubmit={save} className="space-y-4">
      <p className="text-sm text-text-muted">Docker has {(resources.host.memoryBytes / 1024 ** 3).toFixed(1)} GiB RAM and {resources.host.cpus} logical CPUs available. All maps share the available CPU unless you choose an optional limit. Running maps have {resources.reservedMemoryGiB.toFixed(1)} GiB of RAM allocated.</p>
      {!resources.configured && !resources.pending && <p className="text-sm text-text-muted">Existing map RAM limits are shown below. Review and save your per-map allocations.</p>}
      <p className="text-sm text-text-muted">Map RAM limits apply to each running instance. DST checks that starting maps fits within {allocation.memoryGiB} GiB, including {resources.serviceReserveGiB} GiB for supporting services and leaving another 2 GiB for the host.</p>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={showCpuLimits} onChange={e => setShowCpuLimits(e.target.checked)} />Show optional per-map CPU limits</label>
      {resources.worldRunning && <p role="status" className="text-warning">Stop the battlegroup before changing allocations. Saving never stops or restarts it for you.</p>}
      {resources.pending && <p role="status" className="text-warning">An allocation was interrupted. Retry the saved allocation to finish verifying its container limits.</p>}
      <button className="btn-primary" type="submit" disabled={blocked}>{busy ? 'Saving…' : resources.pending ? 'Retry allocation' : 'Save allocations'}</button>
      {message && <p role="status" className="text-success">{message}</p>}
      {allocation.maps.length > 0 ? <>
        <label className="block text-sm">Find a map<input className={`${inputClass} w-full`} type="search" placeholder="Search by map name" value={query} onChange={e => setQuery(e.target.value)} /></label>
        <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr><th className="text-left">Map</th><th>RAM per instance (GiB)</th>{showCpuLimits && <th>CPU limit · blank shares all</th>}</tr></thead><tbody>
          {allocation.maps.filter(row => `${row.map} ${mapLabel(row.map)}`.toLowerCase().includes(query.toLowerCase())).map(row => <tr key={row.map}>
            <td className="py-2 pr-3">{mapLabel(row.map)}</td>
            <td className="p-2"><input className={`${inputClass} w-24`} aria-label={`${row.map} RAM`} type="number" min={0.25} max={Math.min(128, allocation.memoryGiB - 2)} step={0.25} required disabled={blocked || resources.pending} value={row.memoryGiB} onChange={e => updateMap(row.map, 'memoryGiB', Number(e.target.value))} /></td>
            {showCpuLimits && <td className="p-2"><input className={`${inputClass} w-24`} aria-label={`${row.map} CPUs`} type="number" placeholder="Shared" min={0.25} max={resources.host.cpus} step={0.25} disabled={blocked || resources.pending} value={row.cpus ?? ''} onChange={e => updateMap(row.map, 'cpus', e.target.value === '' ? null : Number(e.target.value))} /></td>}
          </tr>)}
        </tbody></table></div>
      </> : <p className="text-sm text-text-muted">Per-map controls appear after world setup.</p>}
    </form>}
  </CollapsibleCard>
}
