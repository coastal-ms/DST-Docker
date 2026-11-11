import { useEffect, useState } from 'react'
import { api, withOnlinePlayerGuard } from '../../api/client'

type Backup = { id: string; name: string; originalFilename?: string; phase: string; createdAt: number; verification?: { phase: string } }
type State = { backups: Backup[]; operation?: { id: string; phase: string; error?: string }; restore?: { phase: string } }
type Reply = { ok: boolean; data?: State; error?: string }

export default function DockerRestoreDialog({ onClose, onComplete }: { onClose: () => void; onComplete: () => void }) {
  const [backups, setBackups] = useState<Backup[]>([])
  const [selected, setSelected] = useState('')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    void api<Reply>('/api/docker/setup').then(reply => {
      if (!active) return
      if (!reply.ok || !reply.data) throw new Error(reply.error || 'Could not load backups.')
      const choices = reply.data.backups.filter(backup => backup.phase === 'completed' && backup.verification?.phase === 'completed')
      setBackups(choices); setSelected(choices[0]?.id || '')
    }).catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'Could not load backups.') })
    return () => { active = false }
  }, [])
  async function restore() {
    setBusy(true); setError(''); setProgress('Starting restore…')
    try {
      const reply = await withOnlinePlayerGuard(force => api<Reply>(`/api/docker/setup${force ? '?force=true' : ''}`, { method: 'POST', body: JSON.stringify({ action: 'backups.restore', backupId: selected, confirmation: 'RESTORE' }) }))
      if (!reply.ok || !reply.data?.operation) throw new Error(reply.error || 'Could not start restore.')
      const operationId = reply.data.operation.id
      const deadline = Date.now() + 2 * 60 * 60 * 1000
      while (Date.now() < deadline) {
        await new Promise(resolve => window.setTimeout(resolve, 2000))
        const current = await api<Reply>('/api/docker/setup')
        if (!current.ok || !current.data) throw new Error(current.error || 'Could not read restore progress.')
        const operation = current.data.operation
        const phase = current.data.restore?.phase
        setProgress(phase === 'stopping' ? 'Stopping servers…' : phase === 'preparing' ? 'Preparing restore…' : phase === 'completed' ? 'Starting servers…' : 'Restoring database…')
        if (operation?.id === operationId && operation.phase === 'failed') throw new Error(operation.error || 'Restore failed.')
        if (operation?.id === operationId && operation.phase === 'completed') { onComplete(); return }
      }
      throw new Error('Restore is still running. Check server status before starting another operation.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Restore failed.'); setBusy(false) }
  }
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-labelledby="docker-restore-title">
    <div className="card w-full max-w-xl p-5 sm:p-6">
      <h2 id="docker-restore-title" className="text-lg font-semibold">Restore Backup</h2>
      <p className="mt-3 text-sm text-text-muted">This rolls all players, bases, inventory and world data back to the selected snapshot. Changes made since that snapshot will be replaced.</p>
      <label className="mt-4 block text-sm">Verified backup<select className="input mt-2 w-full" aria-label="Verified backup" disabled={busy} value={selected} onChange={event => setSelected(event.target.value)}>{backups.map(backup => <option key={backup.id} value={backup.id}>{new Date(backup.createdAt * 1000).toLocaleString()} · {backup.originalFilename || backup.name}</option>)}</select></label>
      {!backups.length && <p className="mt-2 text-sm text-warning">Verify a saved backup before restoring it.</p>}
      {busy && <p role="status" className="mt-4 text-sm text-accent">{progress}</p>}
      {error && <p role="alert" className="mt-4 text-sm text-danger">{error}</p>}
      <div className="mt-5 flex justify-end gap-3"><button className="btn-secondary" disabled={busy} onClick={onClose}>Cancel</button><button className="btn-primary" disabled={busy || !selected} onClick={() => void restore()}>Restore selected backup</button></div>
    </div>
  </div>
}
