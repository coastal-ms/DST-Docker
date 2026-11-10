import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../../api/client'
import { CollapsibleCard } from '../../components/CollapsibleCard'

type Settings = { platform: string; available: boolean; message?: string; configuredGiB?: number | null; configuredValue?: string | null; useDefault?: boolean; currentMemoryGiB?: number; defaultMemoryGiB?: number; maxMemoryGiB?: number; restartRequired?: boolean }
export function WslMemoryCard() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [useDefault, setUseDefault] = useState(true)
  const [limit, setLimit] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  function receive(value: Settings) {
    setSettings(value); setUseDefault(value.useDefault === true)
    setLimit(String(value.configuredGiB ?? Math.floor(value.defaultMemoryGiB ?? 1)))
  }
  useEffect(() => {
    let active = true
    api<Settings>('/api/docker/host?detail=memory').then(value => { if (active) receive(value) }).catch(() => { /* The host controls are optional on native Linux. */ })
    return () => { active = false }
  }, [])
  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('')
    try {
      const value = await api<Settings>('/api/docker/host', { method: 'POST', body: JSON.stringify({ action: 'memory.set', memoryGiB: useDefault ? null : Number(limit) }) })
      receive(value); setMessage(value.restartRequired ? 'Saved. The new limit applies after a WSL restart.' : 'WSL RAM setting saved.')
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  if (settings?.platform !== 'wsl') return null
  return <CollapsibleCard id="wsl-memory" title="WSL RAM limit" icon="MemoryStick" subtitle="Set the maximum RAM available to the WSL virtual machine.">
    {!settings.available ? <p className="text-sm text-text-muted">{settings.message || 'Open the DST Docker desktop icon to enable WSL settings.'}</p> : <form onSubmit={save} className="space-y-3">
      <p className="text-sm text-text-muted">WSL currently reports {settings.currentMemoryGiB?.toFixed(1)} GiB RAM. This is a ceiling, not reserved RAM.</p>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={useDefault} disabled={busy} onChange={event => setUseDefault(event.target.checked)} />Use WSL default (50% of Windows RAM: {settings.defaultMemoryGiB?.toFixed(1)} GiB)</label>
      {!useDefault && <label className="block text-sm">RAM limit (GiB)<input type="number" className="map-management-input ml-2 w-24" min="1" max={settings.maxMemoryGiB} step="1" required value={limit} disabled={busy} onChange={event => setLimit(event.target.value)} /></label>}
      <p className="text-sm text-text-muted">Applies to all WSL 2 distributions after a WSL restart. Saving keeps the current server running. Adjust map allocations to fit the new limit before restarting.</p>
      {settings.restartRequired && !message && <p role="status" className="text-sm text-warning">Saved limit: {settings.useDefault ? 'WSL default' : `${settings.configuredValue}`}. WSL restart pending.</p>}
      <button type="submit" className="btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save WSL RAM limit'}</button>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {message && <p role="status" className="text-sm text-success">{message}</p>}
    </form>}
  </CollapsibleCard>
}
