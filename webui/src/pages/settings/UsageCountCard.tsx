import { useEffect, useState } from 'react'
import { api } from '../../api/client'

export function UsageCountCard() {
  const [enabled, setEnabled] = useState(true)
  const [loading, setLoading] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let active = true
    api<{ values: Record<string, string> }>('/api/config').then(result => {
      if (active) {
        const value = (result.values.AnonymousUsageEnabled ?? '').trim()
        setEnabled(!value || /^(true|1|yes|on)$/i.test(value))
        setLoaded(true)
      }
    }).catch(() => { if (active) setError('Could not load the anonymous count setting.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])
  async function change(next: boolean) {
    setSaving(true); setError(null)
    try {
      await api('/api/config', { method: 'PUT', body: JSON.stringify({ values: { AnonymousUsageEnabled: String(next) } }) })
      setEnabled(next)
    } catch { setError('Could not save the anonymous count setting.') }
    finally { setSaving(false) }
  }
  return <section className="card p-5 space-y-3" aria-label="Anonymous usage count">
    <h2 className="text-lg font-semibold">Anonymous usage count</h2>
    <p className="text-sm text-muted">Help show how many DST installations are in use. While DST is open, it reports a random installation ID, the Docker or Windows edition, and the app version every six hours. Server names, addresses, players, accounts, settings, and logs are not included.</p>
    <label className="flex items-center gap-3">
      <input type="checkbox" checked={loaded && enabled} disabled={!loaded || saving}
        onChange={event => void change(event.target.checked)} />
      Share anonymous usage count{loading ? ' — loading…' : !loaded ? ' — unavailable' : saving ? ' — saving…' : enabled ? ' — enabled' : ' — disabled'}
    </label>
    <p className="text-xs text-muted">Enabled by default. You can turn it off at any time. Turning it off requests removal of this installation’s count; old reports expire after 24 hours. The receiving website can see the connection’s IP address.</p>
    {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
  </section>
}
