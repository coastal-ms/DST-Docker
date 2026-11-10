import { useEffect, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { api } from '../../api/client'

type Mode = 'private' | 'public'
type Status = { mode: Mode | 'off'; phase: string; busy?: boolean; url?: string; loginUrl?: string; message?: string }
export function DockerTailscaleAccess() {
  const [status, setStatus] = useState<Status | null>(null)
  const [mode, setMode] = useState<Mode>('private')
  const [error, setError] = useState('')
  const [readError, setReadError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    let cancelled = false, loading = false, first = true
    const refresh = async () => {
      if (loading) return
      loading = true
      try {
        const value = await api<Status>('/api/docker/tailscale')
        if (!cancelled) {
          setStatus(value); setReadError('')
          if (first && value.mode !== 'off') setMode(value.mode)
          first = false
        }
      } catch (e) { if (!cancelled) setReadError(e instanceof Error ? e.message : String(e)) }
      finally { loading = false }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 4000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [])
  const apply = async (selected: Mode | 'off') => {
    if (submitting || status?.busy) return
    setSubmitting(true); setError(''); setCopied(false)
    try { setStatus(await api<Status>('/api/docker/tailscale', { method: 'PUT', body: JSON.stringify({ mode: selected }) })) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setSubmitting(false) }
  }
  const busy = submitting || !!status?.busy
  return <section className="card p-5 space-y-3" aria-label="Tailscale remote access">
    <h2 className="text-lg font-semibold">Remote access with Tailscale</h2>
    <p className="text-sm text-text-muted">Connect from outside your network without forwarding a firewall port. DST runs Tailscale in its own Docker container.</p>
    <label className="block text-sm">Access method<select className="map-management-input mt-1 block" value={mode} disabled={busy} onChange={event => setMode(event.target.value as Mode)}>
      <option value="private">Private · Tailscale devices</option>
      <option value="public">Public HTTPS · Tailscale Funnel</option>
    </select></label>
    <p className="text-sm text-text-muted">{mode === 'private' ? 'Connect your phone or tablet to the same Tailscale network, then open the link and sign in to DST.' : 'Anyone with the HTTPS address can reach the DST sign-in page. They do not need Tailscale. Your DST account permissions still apply.'}</p>
    <div className="flex flex-wrap gap-2">
      <button type="button" className="btn-primary" disabled={!status || busy} onClick={() => void apply(mode)}>{busy ? 'Connecting…' : status?.phase === 'connected' && status.mode === mode ? 'Reconnect' : 'Connect'}</button>
      {status && status.mode !== 'off' && <button type="button" className="btn-secondary" disabled={busy} onClick={() => void apply('off')}>Turn off</button>}
    </div>
    {(error || readError) && <p role="alert" className="text-sm text-danger">{error || readError}</p>}
    {status?.message && <p role={status.phase === 'failed' ? 'alert' : 'status'} className="text-sm">{status.message}</p>}
    {status?.loginUrl && /^https:\/\/login\.tailscale\.com\//.test(status.loginUrl) && <a className="btn-primary inline-flex" href={status.loginUrl} target="_blank" rel="noreferrer">{status.phase === 'setup-required' ? 'Complete Tailscale setup' : 'Sign in to Tailscale'}</a>}
    {status?.phase === 'connected' && status.url && <div className="flex flex-wrap items-center gap-4">
      <div className="rounded bg-white p-2"><QRCodeSVG value={status.url} size={112} title="Open DST remotely" /></div>
      <div className="space-y-2 min-w-0"><a className="block break-all text-accent" href={status.url} target="_blank" rel="noreferrer">{status.url}</a>
        <button type="button" className="btn-secondary" onClick={() => { void navigator.clipboard.writeText(status.url!).then(() => setCopied(true)).catch(() => setError('Copy the address shown above.')) }}>{copied ? 'Copied' : 'Copy link'}</button>
        <p className="text-xs text-text-muted">Sign in to DST on the connecting device. Game maps keep running when remote access changes.</p>
      </div>
    </div>}
  </section>
}
