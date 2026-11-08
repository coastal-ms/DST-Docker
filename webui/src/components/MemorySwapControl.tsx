import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { usePortalAccess } from '../auth/portalAccess'

type SwapStatus = {
  available: boolean; enabled: boolean; perServerGiB: number; poolGiB: number
  configuredSwappiness: number; existingSwapGiB: number; worldServerCount: number
  safeAvailableDiskGiB: number; hostPoolActive: boolean; swappiness: number
  pending: boolean; error?: string; pendingChange?: { error?: string }
  requiresDefaultRestore?: boolean
  operation?: { id: string; phase: string; error?: string }
}
type Started = { ok: boolean; error?: string; data?: { operation: { id: string } } }
type Mode = 'low' | 'automatic' | 'custom'
const field = 'rounded border border-border bg-surface px-2 py-1 text-text'

export function MemorySwapControl() {
  const { canAccessOwnerSurfaces } = usePortalAccess()
  return canAccessOwnerSurfaces ? <OwnerMemorySwapControl /> : null
}

function OwnerMemorySwapControl() {
  const [status, setStatus] = useState<SwapStatus | null>(null)
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<Mode>('automatic')
  const [allowance, setAllowance] = useState(2)
  const [pool, setPool] = useState(0)
  const [swappiness, setSwappiness] = useState(10)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  function receive(value: SwapStatus) {
    setStatus(value)
    setAllowance(value.perServerGiB || 2); setPool(value.poolGiB)
    setSwappiness(value.configuredSwappiness)
    const recommended = Math.max(0, Math.min(32, (value.perServerGiB || 2) * value.worldServerCount - value.existingSwapGiB))
    setMode(value.configuredSwappiness === 10 && value.poolGiB === recommended && value.perServerGiB === 1 ? 'low'
      : value.configuredSwappiness === 10 && value.poolGiB === recommended && value.perServerGiB === 2 ? 'automatic' : 'custom')
  }
  async function load() {
    try { receive(await api<SwapStatus>('/api/docker/memory-swap')); setError('') }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  useEffect(() => { void load() }, [])
  const selectedAllowance = mode === 'low' ? 1 : mode === 'automatic' ? 2 : allowance
  const selectedPool = mode === 'custom' ? pool : Math.max(0, Math.min(32, selectedAllowance * (status?.worldServerCount || 2) - (status?.existingSwapGiB || 0)))
  const selectedSwappiness = mode === 'custom' ? swappiness : 10
  async function wait(started: Started) {
    if (!started.ok || !started.data) throw new Error(started.error || 'Memory Swap could not start.')
    const id = started.data.operation.id, end = Date.now() + 20 * 60 * 1000
    while (Date.now() < end) {
      const current = await api<SwapStatus>('/api/docker/memory-swap')
      setStatus(current)
      if (current.operation?.id !== id) throw new Error('The recorded Memory Swap operation changed. Refresh its status before retrying.')
      if (['failed', 'interrupted'].includes(current.operation.phase)) throw new Error(current.operation.error || 'Memory Swap needs recovery.')
      if (current.operation.phase === 'completed') { receive(current); return }
      await new Promise(resolve => window.setTimeout(resolve, 1000))
    }
    throw new Error('Memory Swap is still pending. Refresh its recorded status before retrying.')
  }
  async function change(enabled: boolean) {
    if (!status) return
    if (enabled && (!Number.isInteger(selectedAllowance) || selectedAllowance < 1 || selectedAllowance > 16
      || !Number.isInteger(selectedPool) || selectedPool < 0 || selectedPool > 32
      || !Number.isInteger(selectedSwappiness) || selectedSwappiness < 0 || selectedSwappiness > 100)) {
      setError('Use 1–16 GiB per running map, a 0–32 GiB managed pool, and swappiness from 0–100.'); return
    }
    if (enabled && selectedPool > status.safeAvailableDiskGiB) { setError('The selected pool would consume the host disk safety reserve.'); return }
    const review = enabled
      ? `Enable Memory Swap?\n\nExisting host swap: ${status.existingSwapGiB} GiB\nAdditional managed swap: ${selectedPool} GiB\nEmergency allowance per running map: ${selectedAllowance} GiB\nHost swappiness: ${selectedSwappiness}\nDisk reserve: at least 25 GiB or 10%\n\nMap RAM limits stay unchanged. Disk-backed memory can increase loading time and lag.`
      : 'Disable Memory Swap?\n\nRestore Docker’s default swap allowance and remove only this installation’s managed swap file. Administrator-managed host swap remains available. Host swappiness is restored only if DST still owns the current value.'
    if (!window.confirm(review)) return
    setBusy(true); setError(''); setMessage('Applying Memory Swap…')
    try {
      await wait(await api<Started>('/api/docker/memory-swap', { method: 'PUT', body: JSON.stringify({ enabled, perServerGiB: selectedAllowance, poolGiB: selectedPool, swappiness: selectedSwappiness, confirmation: enabled ? 'ENABLE MEMORY SWAP' : 'DISABLE MEMORY SWAP' }) }))
      setMessage(enabled ? 'Memory Swap saved and verified. Running and newly started maps retain this allowance.' : 'Memory Swap disabled. Docker’s default swap behavior is restored.')
    } catch (e) { const failure=e instanceof Error ? e.message : String(e); setMessage(''); await load(); setError(failure) }
    finally { setBusy(false) }
  }
  async function recover(restorePrevious: boolean) {
    if (!window.confirm(restorePrevious ? 'Restore the Memory Swap policy from before the interrupted change?' : 'Retry the recorded Memory Swap change?')) return
    setBusy(true); setError(''); setMessage('Recovering Memory Swap…')
    try {
      await wait(await api<Started>('/api/docker/memory-swap/recover', { method: 'POST', body: JSON.stringify({ restorePrevious, confirmation: 'RECOVER MEMORY SWAP' }) }))
      setMessage('Memory Swap recovery completed.')
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); setMessage('') }
    finally { setBusy(false) }
  }
  const blocked = busy || status?.operation?.phase === 'running'
  return <section className="mt-3 border-t border-border/40 pt-3" aria-label="Memory Swap controls">
    <button type="button" className="btn-secondary min-h-10" aria-expanded={open} onClick={() => setOpen(!open)}>Memory Swap: {status ? status.enabled ? 'On' : 'Off' : 'Loading…'}</button>
    {open && <div className="mt-3 space-y-3 text-sm">
      <p className="text-text-dim">Disk-backed emergency memory is separate from memory balancing. Your map RAM limits stay unchanged.</p>
      {!status?.available ? <p role="status">{status?.error || 'Host swap information is unavailable.'} <button type="button" className="btn-secondary" onClick={() => { void load() }}>Refresh swap status</button></p> : <>
        <p>Existing host swap: {status.existingSwapGiB} GiB. Managed pool: {status.poolGiB} GiB ({status.hostPoolActive ? 'active' : 'inactive'}). Host swappiness: {status.swappiness}.</p>
        {status.requiresDefaultRestore && <p role="status" className="text-text-dim">Existing maps retain their previous swap limits. Apply Memory Swap or explicitly restore Docker’s default allowance below. RAM limits stay unchanged.</p>}
        <label className="flex items-center gap-2">Mode<select aria-label="Memory Swap mode" className={field} disabled={blocked || status.pending} value={mode} onChange={e => setMode(e.target.value as Mode)}><option value="low">Low · 1 GiB per map</option><option value="automatic">Automatic · 2 GiB per map</option><option value="custom">Custom</option></select></label>
        {mode === 'custom' && <div className="flex flex-wrap gap-3">
          <label>Swap per map (GiB)<input aria-label="Swap per map" className={`${field} ml-2 w-20`} type="number" min={1} max={16} step={1} disabled={blocked || status.pending} value={allowance} onChange={e => setAllowance(Number(e.target.value))} /></label>
          <label>Managed pool (GiB)<input aria-label="Managed swap pool" className={`${field} ml-2 w-20`} type="number" min={0} max={32} step={1} disabled={blocked || status.pending} value={pool} onChange={e => setPool(Number(e.target.value))} /></label>
          <label>Swappiness<input aria-label="Swap swappiness" className={`${field} ml-2 w-20`} type="number" min={0} max={100} step={1} disabled={blocked || status.pending} value={swappiness} onChange={e => setSwappiness(Number(e.target.value))} /></label>
        </div>}
        <p className="text-text-dim">Selected: {selectedAllowance} GiB per running map, {selectedPool} GiB additional managed swap, swappiness {selectedSwappiness}. Automatic sizing accounts for existing host swap and at least two running maps. At least 25 GiB or 10% of the host disk stays free.</p>
        {status.pending ? <div role="status" className="space-y-2"><p>{status.pendingChange?.error || 'A Memory Swap change is pending.'}</p><button type="button" className="btn-primary mr-2" disabled={blocked} onClick={() => { void recover(false) }}>Retry Memory Swap</button><button type="button" className="btn-secondary" disabled={blocked} onClick={() => { void recover(true) }}>Restore previous swap policy</button></div>
          : <div className="flex flex-wrap gap-2"><button type="button" className="btn-primary" disabled={blocked} onClick={() => { void change(true) }}>{status.enabled ? 'Apply Memory Swap' : 'Enable Memory Swap'}</button>{(status.enabled || status.requiresDefaultRestore) && <button type="button" className="btn-secondary" disabled={blocked} onClick={() => { void change(false) }}>{status.enabled ? 'Disable Memory Swap' : 'Restore Docker default swap'}</button>}</div>}
      </>}
    </div>}
    {message && <p role="status" className="mt-2 text-xs text-text-muted">{message}</p>}
    {error && <p role="alert" className="mt-2 text-xs text-danger">{error}</p>}
  </section>
}
