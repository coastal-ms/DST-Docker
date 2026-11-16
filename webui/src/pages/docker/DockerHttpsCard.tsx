import { useEffect, useState } from 'react'
import { api, authenticatedApiNavigation } from '../../api/client'
import { confirmAction } from '../../util/actionConfirmation'

type HttpsState = { supported: boolean; enabled: boolean; prepared: boolean; url: string; address: string; port: number; addresses: string[]; sha256?: string; certificateAvailable: boolean; error?: string; operation?: { id: string; phase: string; action: string; message: string } }

export function DockerHttpsCard() {
  const [state, setState] = useState<HttpsState | null>(null)
  const [address, setAddress] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [trusted, setTrusted] = useState(false)
  const [changing, setChanging] = useState<'enable' | 'disable' | null>(null)
  useEffect(() => { setTrusted(false) }, [state?.sha256])
  useEffect(() => {
    let cancelled = false, loading = false
    const load = async () => {
      if (loading) return
      loading = true
      try {
        const value = await api<HttpsState>('/api/docker/https')
        if (!cancelled) {
          setState(value)
          setAddress(current => current || value.address || (value.addresses?.includes(window.location.hostname) ? window.location.hostname : value.addresses?.[0] ?? ''))
          setError('')
        }
      } catch (e) { if (!cancelled) setError(e instanceof Error ? e.message : String(e)) }
      finally { loading = false }
    }
    void load()
    const timer = window.setInterval(() => void load(), 4000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [])
  const busy = submitting || state?.operation?.phase === 'running'
  const apply = async (action: 'prepare' | 'enable' | 'disable') => {
    if (busy) return
    if (action === 'disable' && !confirmAction('Return this portal to HTTP? Browser traffic on the host address will no longer be encrypted. Existing certificates and game maps are kept.')) return
    setSubmitting(true); setError('')
    if (action !== 'prepare') setChanging(action)
    try {
      setState(await api<HttpsState>('/api/docker/https', { method: 'POST', body: JSON.stringify(action === 'prepare' ? { action, address } : action === 'enable' ? { action, sha256: state?.sha256 } : { action }) }))
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setSubmitting(false) }
  }
  const safeUrl = state?.url && /^https:\/\/\d{1,3}(?:\.\d{1,3}){3}:\d{4,5}$/.test(state.url) ? state.url : ''
  return <section className="card p-5 space-y-4" aria-label="Browser HTTPS">
    <div><h2 className="text-lg font-semibold">Browser HTTPS</h2><p className="mt-1 text-sm text-text-muted">Encrypt connections to this Docker portal. Game maps keep running during setup.</p></div>
    <p className="text-sm">This browser: <strong>{window.location.protocol === 'https:' ? 'HTTPS' : 'HTTP'}</strong>. {window.location.protocol !== 'https:' && 'The current connection is not encrypted.'}</p>
    {!state && !error && <p role="status">Reading HTTPS settings…</p>}
    {state?.supported === false && <p role="status">{state.error || 'HTTPS setup is not connected to this installation. Rerun the installer in the same folder to connect the host service.'}</p>}
    {state?.supported && <>
      <p className="text-sm">Local HTTPS: <strong>{state.enabled ? 'Enabled' : 'Not enabled'}</strong></p>
      {!state.enabled && <div className="space-y-3">
        <label className="block text-sm">Host address<select className="map-management-input mt-1 block" value={address} disabled={busy} onChange={event => { setAddress(event.target.value); setTrusted(false) }}>
          <option value="">Choose an address</option>
          {(state.addresses ?? []).map(value => <option key={value} value={value}>{value}</option>)}
        </select></label>
        <p className="text-sm text-text-muted">1. Prepare HTTPS. Your current HTTP connection stays available.</p>
        <button type="button" className="btn-secondary" disabled={busy || !address} onClick={() => void apply('prepare')}>Prepare HTTPS</button>
      </div>}
      {state.certificateAvailable && <div className="space-y-3">
        <p className="text-sm text-text-muted">{!state.enabled && '2. '}Download this installation’s public certificate and trust it on each device you use. Downloading alone does not install it.</p>
        <a className="btn-secondary inline-flex" href={authenticatedApiNavigation('/api/docker/https/certificate')} download="dst-docker-root.crt">Download certificate</a>
        <div className="text-xs text-text-muted">Certificate SHA-256<div className="mt-1 font-mono break-all select-all">{state.sha256}</div></div>
        <details className="text-sm"><summary className="cursor-pointer text-accent">Certificate trust instructions</summary><div className="mt-2 space-y-2 text-text-muted">
          <p>Windows: open the downloaded certificate, choose Install Certificate, select Current User, then place it in Trusted Root Certification Authorities. Confirm only the certificate from your own DST installation.</p>
          <p>Other devices: import this public CA into that device’s trusted certificate store. Some browsers use a separate certificate store. You must repeat this for each device; DST never installs trust automatically.</p>
          <p>For player access without installing this local certificate, use the existing Tailscale HTTPS options below or your own trusted HTTPS reverse proxy.</p>
        </div></details>
      </div>}
      {!state.enabled && state.prepared && state.address === address && <div className="space-y-3">
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={trusted} disabled={busy} onChange={event => setTrusted(event.target.checked)} />I have trusted this certificate on this device.</label>
        <p className="text-sm text-text-muted">3. Enable HTTPS, then open the HTTPS portal. Sign in again if prompted.</p>
        <button type="button" className="btn-primary" disabled={busy || !trusted || !state.sha256} onClick={() => void apply('enable')}>Enable HTTPS</button>
      </div>}
      {safeUrl && (state.enabled || changing === 'enable') && <a className="btn-primary inline-flex" href={safeUrl + '/settings'}>Open HTTPS portal</a>}
      {state.enabled && <button type="button" className="btn-secondary" disabled={busy} onClick={() => void apply('disable')}>Return to HTTP</button>}
      {changing === 'disable' && safeUrl && <a className="btn-secondary inline-flex" href={safeUrl.replace('https:', 'http:') + '/settings'}>Open HTTP portal</a>}
      {state.operation && <p role={state.operation.phase === 'failed' ? 'alert' : 'status'} className="text-sm">{state.operation.message}</p>}
      {changing && <p className="text-sm text-text-muted">The portal may disconnect briefly. After the connection changes, use the link above. Existing HTTP bookmarks redirect when HTTPS is enabled.</p>}
    </>}
    {error && <p role="alert" className="text-sm text-danger">{error}</p>}
  </section>
}
