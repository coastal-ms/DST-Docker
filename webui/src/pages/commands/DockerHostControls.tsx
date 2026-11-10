import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { usePortalAuth } from '../../auth/PortalAuthGate'

type HostStatus = { available: boolean; platform?: string; busy?: boolean; phase?: string; message: string }
export function DockerHostControls() {
  const auth = usePortalAuth()
  const [status, setStatus] = useState<HostStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [shuttingDown, setShuttingDown] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const owner = auth?.status.account?.role === 'owner'
  useEffect(() => {
    if (!owner) return
    let active = true
    const refresh = async () => {
      try {
        const result = await api<HostStatus>('/api/docker/host')
        if (active) { setStatus(result); if (result.phase === 'failed') { setError(result.message); setShuttingDown(false) } }
      } catch {
        if (active && !shuttingDown) setStatus({ available: false, message: 'Start DST using its desktop icon to enable WSL host controls.' })
      }
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 2000)
    return () => { active = false; window.clearInterval(timer) }
  }, [owner, shuttingDown])
  if (!owner || status?.platform === 'linux') return null
  async function act(action: 'shortcut' | 'shutdown') {
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await api<{ path?: string }>('/api/docker/host', { method: 'POST', body: JSON.stringify({ action, confirmation: action === 'shutdown' ? 'SHUT DOWN HOST' : undefined }) })
      if (action === 'shutdown') { setShuttingDown(true); setNotice('Shutting down: stopping the battlegroup, then DST containers and WSL. This page will disconnect. Use the DST Docker desktop icon to start again.') }
      else setNotice(`Desktop shortcut created${result.path ? `: ${result.path}` : '.'}`)
    } catch (e) { setError(e instanceof Error ? e.message : 'Host action failed.') }
    finally { setBusy(false) }
  }
  const disabled = busy || shuttingDown || status?.busy || !status?.available
  return <section className="card p-4 space-y-3" aria-label="Windows host controls">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="font-semibold">Windows host</h2><p className="text-sm text-text-muted">Start with the DST Docker desktop icon. Stop the battlegroup and WSL here.</p></div>
      <div className="flex flex-wrap gap-2">
        <button className="btn-secondary" disabled={disabled} onClick={() => { void act('shortcut') }}>Create desktop shortcut</button>
        <button className="btn-secondary" disabled={disabled} onClick={() => { void act('shutdown') }}>{status?.busy && status.phase === 'recovering-owner' ? 'Owner recovery…' : status?.busy && status.phase === 'starting' ? 'Starting…' : shuttingDown || status?.busy ? 'Shutting down…' : 'Shut down host'}</button>
      </div>
    </div>
    {!status?.available && <p className="text-sm text-text-muted">{status?.message || 'Checking host session…'}</p>}
    {(notice || status?.busy) && <p role="status" className="text-sm text-warning">{status?.busy ? status.message : notice}</p>}
    {error && <p role="alert" className="text-sm text-danger">{error}</p>}
  </section>
}
