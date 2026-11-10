import { QRCodeSVG } from 'qrcode.react'
import { usePortalAuth } from '../../auth/PortalAuthGate'
import { isLocalViewer } from '../../util/viewer'
import { useEffect, useState } from 'react'
import { api } from '../../api/client'

export function remoteMapLink(origin: string, accountLogin: boolean, existingKey = '') {
  const url = new URL('/map?view=live', origin)
  if (!accountLogin && existingKey) url.searchParams.set('key', existingKey)
  return url.toString()
}

/** Reuse this viewer's portal access; never create or transfer an account session. */
export function RemoteMapQr() {
  const auth = usePortalAuth()
  const [remote, setRemote] = useState<{ url: string; mode: string } | null>(null)
  useEffect(() => {
    if (import.meta.env.VITE_DST_EDITION !== 'docker') return
    let cancelled = false
    const read = () => { void api<{url:string;mode:string}>('/api/map/remote-link').then(value => { if (!cancelled) setRemote(value) }).catch(() => {}) }
    read(); const timer = window.setInterval(read, 15000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [])
  if (isLocalViewer()) return null
  const accountLogin = !!auth?.status.accountLoginEnabled
  const existingKey = accountLogin ? '' : new URL(window.location.href).searchParams.get('key') || window.__duneRemoteToken || ''
  const remoteOrigin = remote?.url && /^https:\/\/[a-z0-9.-]+\.ts\.net$/.test(remote.url) ? remote.url : ''
  const url = remoteMapLink(remoteOrigin || window.location.origin, accountLogin, existingKey)
  return (
    <figure className="m-0 w-40 shrink-0 text-center" aria-label="Open map on phone or tablet">
      <div className="inline-flex rounded-lg bg-white p-2">
        <QRCodeSVG value={url} size={112} marginSize={4} title="Scan to open the live map" />
      </div>
      <figcaption className="mt-1 text-xs text-text-muted">
        Open map on phone or tablet
        {import.meta.env.VITE_DST_EDITION === 'docker' && <span className="block text-text-dim">{remoteOrigin ? remote?.mode === 'private' ? 'Connect Tailscale on that device.' : 'Public HTTPS link.' : 'Uses this console’s network address.'}</span>}
        {accountLogin && <span className="block text-text-dim">Sign in on that device.</span>}
      </figcaption>
    </figure>
  )
}
