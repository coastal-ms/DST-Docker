import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../../api/client'

type Values = { mode: string; switch: string; address: string; prefix: number }
type Settings = { available: boolean; platform: string; dockerIp?: string; settings?: Values; externalSwitches?: string[]; switchDiscoveryError?: string; restartRequired?: boolean; error?: string; message?: string; recoveryShortcut?: string }
export default function DockerLanSettings() {
  const [state, setState] = useState<Settings | null>(null)
  const [values, setValues] = useState<Values>({ mode: 'nat', switch: '', address: '', prefix: 24 })
  const [automatic, setAutomatic] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const switches = state?.externalSwitches ?? []
  const needsSwitch = values.mode === 'bridged'
  const validSelection = !needsSwitch || switches.includes(values.switch)
  function receive(value: Settings) {
    setState(value)
    if (value.settings) {
      const available = value.externalSwitches ?? []
      const savedSwitch = value.settings.switch
      const selectedSwitch = available.includes(savedSwitch) ? savedSwitch : !savedSwitch && available.length === 1 ? available[0] : ''
      setValues({ ...value.settings, switch: selectedSwitch })
      setAutomatic(!value.settings.address)
    }
  }
  useEffect(() => {
    let active = true
    api<Settings>('/api/docker/host?detail=network').then(value => { if (active) receive(value) }).catch(() => {})
    return () => { active = false }
  }, [])
  async function save(event: FormEvent) {
    event.preventDefault()
    if (!validSelection) return
    setBusy(true); setError(''); setMessage('')
    try {
      const value = await api<Settings>('/api/docker/host', { method: 'POST', body: JSON.stringify({ action: 'network.settings.set', settings: { ...values, address: automatic ? '' : values.address } }) })
      receive(value); setMessage('Network settings saved. Shut down the Docker host, then reopen its desktop icon to apply them.')
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  if (state?.platform !== 'wsl') return null
  return <section className="rounded border border-border p-4 space-y-3" aria-label="Docker LAN address configuration">
    <h3 className="font-semibold">Docker LAN address</h3>
    {!state.available ? <p>{state.message || 'Open the desktop icon to configure the Docker host network.'}</p> : <form onSubmit={save} className="space-y-3">
      <p className="text-sm text-text-muted">Current Docker IP: {state.dockerIp || 'Detecting…'}. These controls configure the real host connection. The public address is configured separately below.</p>
      <label className="block text-sm">Host network mode<select className="block mt-1 rounded border border-border bg-surface p-2" disabled={busy} value={values.mode} onChange={e => setValues(v => ({ ...v, mode: e.target.value }))}>
        <option value="nat">Internal WSL address (NAT)</option><option value="mirrored">Share Windows LAN address</option><option value="bridged" disabled={!switches.length}>Own LAN address</option>
      </select></label>
      {!switches.length && <p className="text-sm text-text-muted">{state.externalSwitches === undefined
        ? 'Use Commands > Shut down host, then reopen DST Docker from the desktop icon to load external switch detection.'
        : state.switchDiscoveryError || 'No external switches are available for Own LAN address.'}</p>}
      {needsSwitch && switches.length > 0 && <>
        <p className="text-sm text-text-muted">Uses WSL bridged networking, which Microsoft marks deprecated. Select the external switch connected to your LAN.</p>
        <label className="block text-sm">External switch<select className="block mt-1 rounded border border-border bg-surface p-2" required disabled={busy} value={values.switch} onChange={e => setValues(v => ({ ...v, switch: e.target.value }))}>
          <option value="" disabled>Select an external switch</option>
          {switches.map(name => <option key={name} value={name}>{name}</option>)}
        </select></label>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={automatic} disabled={busy} onChange={e => setAutomatic(e.target.checked)} />Get a LAN IP automatically (DHCP)</label>
        {!automatic && <>
          <label className="block text-sm">Dedicated Docker IPv4<input className="block mt-1 rounded border border-border bg-surface p-2" required disabled={busy} value={values.address} onChange={e => setValues(v => ({ ...v, address: e.target.value }))} /></label>
          <label className="block text-sm">Subnet prefix<input className="block mt-1 rounded border border-border bg-surface p-2" type="number" min="8" max="30" required disabled={busy} value={values.prefix} onChange={e => setValues(v => ({ ...v, prefix: Number(e.target.value) }))} /></label>
          <p className="text-sm text-text-muted">Choose an unused address on the switch’s LAN. Docker checks for an address conflict before assigning it. The existing LAN gateway and DNS remain in use.</p>
        </>}
      </>}
      <p className="text-sm text-text-muted">Network mode applies to all WSL 2 distributions after WSL restarts. Saving keeps the current server running.</p>
      {(error || state.error) && <p role="alert" className="text-danger">{error || state.error}</p>}
      {state.restartRequired && <p className="text-warning text-sm">Host network change pending. Restart the Docker host to apply it.</p>}
      {state.recoveryShortcut && <p className="text-sm text-text-muted">If the new network prevents startup, run the desktop shortcut <strong>Recover Docker network</strong> to restore the previous WSL configuration.</p>}
      <button type="submit" className="btn-secondary" disabled={busy || !validSelection}>{busy ? 'Saving…' : 'Save Docker network'}</button>
      {message && <p role="status" className="text-success">{message}</p>}
    </form>}
  </section>
}
