import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import { ConfirmationModal } from '../../components/ConfirmationModal'

type Snapshot = { available: boolean; platform: string; publicIp?: string; target?: string | null; multiple?: boolean; message?: string; operation?: { id: string; phase: string; error?: string } }

export default function DockerLoopbackSettings({ publicIp, dockerIp }: { publicIp: string; dockerIp: string }) {
  const [state, setState] = useState<Snapshot | null>(null)
  const [choice, setChoice] = useState('existing')
  const [custom, setCustom] = useState('')
  const [posting, setPosting] = useState(false)
  const [pending, setPending] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const initialized = useRef(false)
  const endpoint = '/api/docker/host?detail=loopback&publicIp=' + encodeURIComponent(publicIp)
  useEffect(() => {
    let active = true
    setRefreshing(true)
    api<Snapshot>(endpoint).then(value => {
      if (!active) return
      if (!value.available) {
        setState(previous => previous ? { ...previous, available: false } : value)
        setError(value.message || 'The host check is unavailable. Refresh to retry.'); return
      }
      setState(value); setError('')
      if (!initialized.current) { setCustom(value.target || ''); initialized.current = true }
      if (value.operation?.phase === 'running') setPending(value.operation.id)
    }).catch(e => { if (active) { setState(previous => previous ? { ...previous, available: false } : previous); setError(e instanceof Error ? e.message : String(e)) } })
      .finally(() => { if (active) setRefreshing(false) })
    return () => { active = false }
  }, [endpoint, refreshKey])
  useEffect(() => {
    if (!pending) return
    let active = true, loading = false
    const timer = window.setInterval(async () => {
      if (loading) return
      loading = true
      try {
        const value = await api<Snapshot>(endpoint)
        if (!active) return
        if (!value.available) { setError(value.message || 'The host check is unavailable. Retrying…'); return }
        setState(value)
        if (value.operation?.id !== pending) { setPending(null); setError('The loopback operation changed. Review the current target before retrying.') }
        else if (value.operation.phase !== 'running') {
          setPending(null)
          if (value.operation.phase === 'completed') { setChoice('existing'); setCustom(value.target || ''); setMessage('Loopback target applied.'); setError('') }
          else setError(value.operation.error || 'The loopback target was not changed.')
        }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : String(e)) }
      finally { loading = false }
    }, 2500)
    return () => { active = false; window.clearInterval(timer) }
  }, [pending, endpoint])
  const target = choice === 'router' ? null : choice === 'docker' ? dockerIp : choice === 'custom' ? custom.trim() : state?.target ?? null
  const busy = posting || !!pending
  const changed = !!state?.available && target !== (state.target ?? null)
  async function apply() {
    if (!state?.available || !changed || busy) return
    setConfirming(false); setPosting(true); setError(''); setMessage('')
    try {
      const value = await api<Snapshot>('/api/docker/host', { method: 'POST', body: JSON.stringify({ action: 'loopback.set', publicIp, target, expectedTarget: state.target ?? null, confirmation: 'CHANGE LOOPBACK TARGET' }) })
      setState(value)
      if (value.operation?.phase === 'running') setPending(value.operation.id)
      else { setChoice('existing'); setMessage('Loopback target applied.') }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setPosting(false) }
  }
  return <section className="rounded border border-border p-4 space-y-3" aria-label="Same-PC loopback target">
    <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">Same-PC public-IP loopback</h3><button type="button" className="btn-secondary" disabled={refreshing || busy} onClick={() => setRefreshKey(value => value + 1)}>{refreshing ? 'Refreshing loopback…' : 'Refresh loopback'}</button></div>
    <p className="text-sm">Choose where this Windows PC sends connections to {publicIp}. This affects playing from this PC; outside players use your router forwarding.</p>
    {state?.target !== undefined ? <>
      <p className="text-sm">Current target: <strong>{state.target || 'Router NAT loopback (no same-PC route)'}</strong></p>
      <label className="block text-sm">Loopback target<select className="block mt-1 rounded border border-border bg-surface p-2" value={choice} disabled={busy} onChange={e => { setChoice(e.target.value); setMessage('') }}>
        <option value="existing">Keep current target</option>
        <option value="docker" disabled={!dockerIp}>Docker ({dockerIp || 'detecting…'})</option>
        <option value="custom">Another server IP</option>
        <option value="router">Use router NAT loopback</option>
      </select></label>
      {choice === 'custom' && <label className="block text-sm">Server IPv4 address<input className="block mt-1 rounded border border-border bg-surface p-2" value={custom} disabled={busy} onChange={e => setCustom(e.target.value)} /></label>}
      <p className="text-sm text-text-muted">The current route stays unchanged until you apply this control. Applying player access does not change this target.</p>
      {state.multiple && <p className="text-warning text-sm">Multiple routes exist for this public IP. Review those Windows routes before changing the target.</p>}
      <button type="button" className="btn-secondary" disabled={busy || refreshing || !changed || state.multiple || (target !== null && !target)} onClick={() => setConfirming(true)}>{busy ? 'Applying loopback…' : 'Apply loopback target'}</button>
    </> : <p className="text-sm text-text-muted">{state?.message || 'Reading the Windows loopback route…'}</p>}
    {busy && <p role="status" className="text-sm">Approve the Windows permission prompt to apply the loopback target. The game server keeps running.</p>}
    {error && <p role="alert" className="text-danger">{error}</p>}
    {message && <p role="status" className="text-success">{message}</p>}
    {confirming && <ConfirmationModal title="Change same-PC loopback target?" description={target ? `Connections from this Windows PC to ${publicIp} will go to ${target}, replacing the current target ${state?.target || 'router NAT loopback'}. The game server will keep running.` : `Remove the same-PC route for ${publicIp} and use your router’s NAT loopback instead. The game server will keep running.`} confirmLabel="Apply loopback target" onCancel={() => setConfirming(false)} onConfirm={() => void apply()} />}
  </section>
}
