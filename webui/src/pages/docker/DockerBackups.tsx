import { useEffect, useState } from 'react'
import { api } from '../../api/client'

type Backup = { id: string; name: string; originalFilename?: string; phase: string; createdAt: number; bytes?: number; error?: string; verification?: { phase: string; error?: string; restored?: { duneTables: number; partitions: number; players: number } } }
type State = { phase: string; backups: Backup[]; operation: null | { phase: string; error?: string } }
type Reply = { ok: boolean; data?: State; error?: string }

export default function DockerBackups() {
  const [state, setState] = useState<State | null>(null)
  const [posting, setPosting] = useState(false)
  const [error, setError] = useState('')
  const working = posting || state?.operation?.phase === 'running' || state?.backups.some(backup => ['preparing', 'running'].includes(backup.phase) || ['preparing', 'running'].includes(backup.verification?.phase || ''))
  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const result = await api<Reply>('/api/docker/setup')
        if (active) { if (result.ok && result.data) setState(result.data); else setError(result.error || 'Backups are unavailable.') }
      } catch { if (active) setError('Could not connect to backup services.') }
    }
    void load()
    const timer = window.setInterval(() => void load(), 10000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])
  async function perform(action: string, backupId?: string) {
    setPosting(true); setError('')
    try {
      const result = await api<Reply>('/api/docker/setup', { method: 'POST', body: JSON.stringify({ action, backupId }) })
      if (!result.ok || !result.data) throw new Error(result.error || 'Backup action failed.')
      setState(result.data)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Backup action failed.') }
    finally { setPosting(false) }
  }
  return <section className="dc-section">
    {(error || state?.operation?.error) && <div role="alert" className="dc-notice">{error || state?.operation?.error}</div>}
    <div className="dc-section-title"><h2>Database backups</h2><button className="dc-action" disabled={working || state?.phase !== 'database-ready'} onClick={() => void perform('backups.create')}>Create backup</button></div>
    {working && <div role="status" className="dc-notice">Backup operation in progress…</div>}
    {state && !state.backups.length && <div className="dc-empty">No database backups yet.</div>}
    <div className="dc-backup-list">{state?.backups.map(backup => <article className="dc-setup-card" key={backup.id}>
      <h3>{new Date(backup.createdAt * 1000).toLocaleString()}</h3>
      <p className="break-all">{backup.originalFilename || backup.name}</p>
      <p>{backup.phase === 'completed' ? `${((backup.bytes || 0) / 1024 ** 2).toFixed(1)} MiB · Saved` : backup.phase}</p>
      {backup.error && <p role="alert">{backup.error}</p>}
      {backup.verification?.error && <p role="alert">{backup.verification.error}</p>}
      {backup.verification?.phase === 'completed' ? <span className="dc-connected">Restore verified</span> : <button className="dc-action" disabled={working || backup.phase !== 'completed'} onClick={() => void perform('backups.verify', backup.id)}>Verify restore</button>}
    </article>)}</div>
  </section>
}
