import { confirmAction } from '../../util/actionConfirmation'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'
import { CollapsibleCard } from '../../components/CollapsibleCard'
import { Icon } from '../../components/Icon'

type Mirror = { available: boolean; enabled: boolean; folder: string; phase: string; error?: string; lastCopiedAt?: number; protectedBackups: number }
type Reply = { ok: boolean; error?: string; data?: { backupMirror?: Mirror } }
export function DockerBackupMirror() {
  const [mirror, setMirror] = useState<Mirror | null>(null)
  const [posting, setPosting] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const load = useCallback(async () => {
    const reply = await api<Reply>('/api/docker/setup')
    if (!reply.ok || !reply.data?.backupMirror) throw new Error(reply.error || 'Backup mirror status is unavailable. Refresh to retry.')
    setMirror(reply.data.backupMirror)
  }, [])
  useEffect(() => {
    let closed = false
    const refresh = () => { void load().catch(e => { if (!closed) setError(e instanceof Error ? e.message : String(e)) }) }
    refresh(); const timer = window.setInterval(refresh, 10000)
    return () => { closed = true; window.clearInterval(timer) }
  }, [load])
  async function perform(action: string, enabled?: boolean) {
    if (action === 'backups.mirror.cancel' && !confirmAction('Stop retrying this failed mirror batch? Original backups and existing mirror copies are kept. Main backup retention may prune the originals afterward.')) return
    setPosting(true); setError(''); setMessage('')
    try {
      const reply = await api<Reply>('/api/docker/setup', { method: 'POST', body: JSON.stringify({ action, ...(enabled === undefined ? {} : { enabled }) }) })
      if (!reply.ok) throw new Error(reply.error || 'The backup mirror action could not be completed.')
      await load()
      if (enabled !== undefined) setMessage(enabled ? 'Mirroring enabled. Copies continue while the management service is running.' : 'Mirroring paused. Existing copies are kept; an active copy can finish.')
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setPosting(false) }
  }
  const copying = mirror?.phase === 'preparing' || mirror?.phase === 'running'
  return <CollapsibleCard id="database.backupMirror" icon="FolderSync" title="Local backup mirror">
    <p className="text-sm text-text-muted mb-3">Keep additional copies in a folder on the Docker host. DST never deletes these copies when the main backup files are pruned or deleted. Copying continues independently of this browser.</p>
    {!mirror ? <p role="status" className="text-sm text-text-muted mb-3">Loading backup mirror…</p> : !mirror.available ? <p className="text-sm text-text-muted mb-3">From your DST installation folder on the Docker host, run <code>sh bin/dst-docker up</code> to prepare the backup folder, then refresh here. Copying stays off until you enable it.</p> : <div className="mb-3">
      <span className="text-xs text-text-muted">Folder on the Docker host</span>
      <div className="flex items-center gap-2"><code className="text-xs break-all flex-1">{mirror.folder}</code><button className="btn-secondary" type="button" onClick={() => {
        void (navigator.clipboard ? navigator.clipboard.writeText(mirror.folder) : Promise.reject(new Error('Clipboard unavailable'))).then(() => setMessage('Folder path copied.')).catch(() => setMessage('Select and copy the folder path above.'))
      }}><Icon name="Copy" size={13} />Copy folder path</button></div>
    </div>}
    <label className="flex items-start gap-2 text-sm mb-3"><input type="checkbox" checked={mirror?.enabled ?? false} disabled={posting || (!mirror?.available && !mirror?.enabled)} onChange={e => void perform('backups.mirror.set', e.target.checked)} /><span>Mirror backups to this folder</span></label>
    <div className="flex flex-wrap gap-2 mb-3">
      <button type="button" className="btn-secondary" disabled={posting || !mirror?.available || !mirror.enabled || copying || mirror.phase === 'failed'} onClick={() => void perform('backups.mirror.sync')}>Copy now</button>
      <button type="button" className="btn-secondary" disabled={posting} onClick={() => { setError(''); void load().catch(e => setError(e instanceof Error ? e.message : String(e))) }}>Refresh mirror</button>
      {mirror?.phase === 'failed' && <><button type="button" className="btn-secondary" disabled={posting || !mirror.available} onClick={() => void perform('backups.mirror.recover')}>Retry copy</button><button type="button" className="btn-secondary" disabled={posting} onClick={() => void perform('backups.mirror.cancel')}>Cancel failed batch</button></>}
    </div>
    {copying && <p role="status" className="text-sm text-text-muted">Copying backups… Source backups are kept until this copy finishes.</p>}
    {mirror?.lastCopiedAt && <p className="text-xs text-text-muted">Last successful copy check: {new Date(mirror.lastCopiedAt * 1000).toLocaleString()}</p>}
    {mirror?.phase === 'failed' && mirror.protectedBackups > 0 && <p className="text-xs text-text-muted mt-2">This pending batch keeps {mirror.protectedBackups} source backup(s) from being pruned until you retry or cancel it.</p>}
    {(error || mirror?.error) && <p role="alert" className="text-danger text-sm mt-2">{error || mirror?.error}</p>}
    {message && <p role="status" className="text-text-muted text-sm mt-2">{message}</p>}
  </CollapsibleCard>
}
