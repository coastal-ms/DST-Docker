import { useEffect, useState } from 'react'
import { api } from '../api/client'

export function MemoryBalancingControl() {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    api<{ enabled: boolean }>('/api/docker/memory-balancing').then(value => {
      if (!cancelled) setEnabled(value.enabled)
    }).catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : 'Memory balancing could not be read.') })
    return () => { cancelled = true }
  }, [])
  async function toggle() {
    if (enabled === null) return
    setBusy(true);setError('')
    try {
      const saved = await api<{ enabled: boolean }>('/api/docker/memory-balancing', { method: 'PUT', body: JSON.stringify({ enabled: !enabled }) })
      setEnabled(saved.enabled)
    } catch (e) { setError(e instanceof Error ? e.message : 'Memory balancing could not be saved.') }
    finally { setBusy(false) }
  }
  return <div className="mt-3 border-t border-border/40 pt-3">
    <button type="button" role="switch" aria-checked={enabled === true} aria-label="Memory balancing" disabled={enabled === null || busy} onClick={() => { void toggle() }} className="btn-secondary min-h-10">
      Memory balancing: {busy ? 'Saving…' : enabled === null ? 'Loading…' : enabled ? 'On' : 'Off'}
    </button>
    <p className="mt-2 text-xs text-text-dim">{enabled === false ? 'Classic DST behavior: the usual map startup and Warm controls decide which maps stay loaded.' : 'Empty on-demand maps can unload to free RAM. Entering a cold map takes longer; Warm keeps a chosen map ready.'}</p>
    {error && <p role="alert" className="mt-2 text-xs text-danger">{error}</p>}
  </div>
}
