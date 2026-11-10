import { confirmAction } from '../../util/actionConfirmation'
import { useEffect, useState } from 'react'
import { api } from '../../api/client'

type State = {
  phase: string
  desiredState?: string
  database?: { state: string; health: string }
  services: Array<{ state: string }>
  backups: Array<{ phase: string; verification?: { phase: string } }>
  operation?: { id: string; phase: string; error?: string }
}
type Reply = { ok: boolean; data?: State; error?: string }
export function DockerDatabaseControl({ onChanged, onReadyChange }: { onChanged: () => void; onReadyChange?: (ready: boolean) => void }) {
  const [state, setState] = useState<State | null>(null)
  const [posting, setPosting] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let closed = false
    const load = async () => {
      try {
        const reply = await api<Reply>('/api/docker/setup')
        if (!reply.ok || !reply.data) throw new Error(reply.error || 'Database control is unavailable.')
        if (!closed) setState(reply.data)
      } catch (e) { if (!closed) { setState(null); setError(e instanceof Error ? e.message : String(e)) } }
    }
    void load(); const timer = window.setInterval(() => void load(), 10000)
    return () => { closed = true; window.clearInterval(timer) }
  }, [])
  useEffect(() => { onReadyChange?.(state?.phase === 'database-ready' && state.database?.state === 'running' && state.database.health === 'healthy') }, [state, onReadyChange])
  const running = state?.database?.state === 'running' || state?.database?.state === 'restarting'
  const busy = posting || state?.operation?.phase === 'running' || state?.backups.some(row => ['preparing', 'running'].includes(row.phase) || ['preparing', 'running'].includes(row.verification?.phase || ''))
  const canStop = state?.desiredState !== 'running' && state?.services.every(row => ['created', 'exited'].includes(row.state))
  async function perform(action: 'database.start' | 'database.stop') {
    if (action === 'database.stop' && !confirmAction('Stop the database service? SQL and backup verification remain unavailable until you start it again. The stopped battlegroup stays stopped.')) return
    setPosting(true); setError('')
    try {
      const started = await api<Reply>('/api/docker/setup', { method: 'POST', body: JSON.stringify({ action }) })
      if (!started.ok || !started.data?.operation?.id) throw new Error(started.error || 'Could not start database maintenance.')
      const id = started.data.operation.id; setState(started.data)
      const deadline = Date.now() + 120000
      while (Date.now() < deadline) {
        const reply = await api<Reply>('/api/docker/setup')
        if (!reply.ok || !reply.data) throw new Error(reply.error || 'Refresh Database to check this operation.')
        setState(reply.data)
        if (reply.data.operation?.id !== id) throw new Error('Another operation replaced this one. Refresh Database to check its result.')
        if (reply.data.operation.phase === 'completed') { onChanged(); return }
        if (['failed', 'interrupted'].includes(reply.data.operation.phase)) throw new Error(reply.data.operation.error || 'Database maintenance needs review.')
        await new Promise(resolve => window.setTimeout(resolve, 1000))
      }
      throw new Error('Database maintenance is still pending. Refresh before retrying.')
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setPosting(false) }
  }
  return <section className="card p-4 mb-4">
    <h2 className="font-semibold mb-2">Database service</h2>
    <p className="text-sm text-text-muted mb-3">Run the database for SQL, backups and restore verification while maps stay stopped. Stop the battlegroup before stopping its database.</p>
    <div className="flex flex-wrap items-center gap-3">
      <span className="text-sm">{state?.database ? running ? `Running · ${state.database.health}` : ['created', 'exited'].includes(state.database.state) ? 'Stopped' : state.database.state : state ? 'Complete database setup first.' : 'Loading database status…'}</span>
      <button className="btn-secondary" disabled={!state?.database || busy || state.phase !== 'database-ready' || (running && !canStop)} onClick={() => void perform(running ? 'database.stop' : 'database.start')}>{posting ? 'Working…' : running ? 'Stop database' : 'Start database'}</button>
    </div>
    {error && <p role="alert" className="text-danger text-sm mt-2">{error}</p>}
  </section>
}
