import { api, authenticatedApiNavigation } from './client'

type Backup = { id: string; name?: string; phase: string; error?: string; verification?: { phase: string; error?: string }; export?: { phase: string; error?: string; download?: string } }
type State = { backups: Backup[]; operation?: { id: string; phase: string; error?: string } }
type Reply = { ok: boolean; data?: State; error?: string }

export async function prepareDockerBackupDownload(path: string): Promise<string> {
  const initial = await api<Reply>('/api/docker/setup')
  const backup = initial.data?.backups.find(row => '/backups/' + row.name === path && row.phase === 'completed')
  if (!initial.ok || !backup) throw new Error('Choose a completed backup from this installation.')
  const started = await api<Reply>('/api/docker/setup', { method: 'POST', body: JSON.stringify({ action: 'backups.export', backupId: backup.id }) })
  if (!started.ok || !started.data) throw new Error(started.error || 'Could not prepare the backup download.')
  const deadline = Date.now() + 2 * 60 * 60 * 1000
  while (Date.now() < deadline) {
    const reply = await api<Reply>('/api/docker/setup')
    if (!reply.ok || !reply.data) throw new Error(reply.error || 'Could not read backup export progress.')
    const record = reply.data.backups.find(row => row.id === backup.id)?.export
    if (record?.phase === 'completed') {
      if (!/^\/api\/docker\/backup-exports\/[a-f0-9]{32}$/.test(record.download || '')) throw new Error('Invalid backup download address.')
      return authenticatedApiNavigation(record.download!)
    }
    if (record?.phase === 'failed') throw new Error(record.error || 'Backup export failed.')
    if (reply.data.operation?.id === started.data?.operation?.id && reply.data.operation?.phase === 'failed') throw new Error(reply.data.operation.error || 'Backup export needs review before retrying.')
    await new Promise(resolve => window.setTimeout(resolve, 1000))
  }
  throw new Error('Backup export is still pending. Check Database before retrying.')
}

export async function waitDockerBackupCleanup(): Promise<void> {
  const deadline = Date.now() + 30 * 60 * 1000
  while (Date.now() < deadline) {
    const reply = await api<{ ok: boolean; error?: string; data?: { backupCleanup?: { phase: string; error?: string }; operation?: { phase: string; action: string; error?: string } } }>('/api/docker/setup')
    if (!reply.ok || !reply.data) throw new Error(reply.error || 'Could not read backup cleanup progress.')
    if (reply.data.backupCleanup?.phase === 'failed') throw new Error(reply.data.backupCleanup.error || 'Backup cleanup needs recovery.')
    const cleanupOperation = reply.data.operation && ['backups.delete', 'backups.cleanup.recover'].includes(reply.data.operation.action)
    if (cleanupOperation && ['failed', 'interrupted'].includes(reply.data.operation!.phase)) throw new Error(reply.data.operation!.error || 'Backup cleanup needs recovery.')
    if (!reply.data.backupCleanup && !(cleanupOperation && reply.data.operation!.phase === 'running')) return
    await new Promise(resolve => window.setTimeout(resolve, 1000))
  }
  throw new Error('Backup cleanup is still pending. Check its status before retrying.')
}

export async function recoverDockerBackupCleanup(): Promise<void> {
  const reply = await api<Reply>('/api/docker/setup', { method: 'POST', body: JSON.stringify({ action: 'backups.cleanup.recover' }) })
  if (!reply.ok) throw new Error(reply.error || 'Could not recover backup cleanup.')
  await waitDockerBackupCleanup()
}

export async function recoverDockerScheduledBackup(): Promise<void> {
  const started = await api<Reply>('/api/docker/setup', { method: 'POST', body: JSON.stringify({ action: 'backups.schedule.recover' }) })
  if (!started.ok || !started.data?.operation?.id) throw new Error(started.error || 'Could not resume the scheduled backup.')
  const id = started.data.operation.id
  const deadline = Date.now() + 120000
  while (Date.now() < deadline) {
    const reply = await api<Reply>('/api/docker/setup')
    if (!reply.ok || !reply.data) throw new Error(reply.error || 'Could not read recovery progress.')
    if (reply.data.operation?.id !== id) throw new Error('Another operation replaced recovery. Refresh Database to check its recorded result.')
    if (reply.data.operation.phase === 'completed') return
    if (['failed', 'interrupted'].includes(reply.data.operation.phase)) throw new Error(reply.data.operation.error || 'Backup recovery needs review.')
    await new Promise(resolve => window.setTimeout(resolve, 1000))
  }
  throw new Error('Backup recovery is still pending. Refresh Database before retrying.')
}

export async function createDockerBackup(): Promise<void> {
  const started = await api<Reply>('/api/docker/setup', { method: 'POST', body: JSON.stringify({ action: 'backups.create' }) })
  if (!started.ok || !started.data) throw new Error(started.error || 'Could not start the backup.')
  const existing = new Set(started.data.backups.map(backup => backup.id))
  const operationId = started.data.operation?.id
  const deadline = Date.now() + 2 * 60 * 60 * 1000
  let verificationRequested = false
  while (Date.now() < deadline) {
    await new Promise(resolve => window.setTimeout(resolve, 2000))
    const reply = await api<Reply>('/api/docker/setup')
    if (!reply.ok || !reply.data) throw new Error(reply.error || 'Could not read backup progress.')
    const backup = reply.data.backups.find(backup => !existing.has(backup.id))
    if (backup?.phase === 'completed') {
      if (backup.verification?.phase === 'completed') return
      if (backup.verification?.phase === 'failed') throw new Error(backup.verification.error || 'Backup verification failed.')
      if (!verificationRequested && !backup.verification) {
        const verification = await api<Reply>('/api/docker/setup', { method: 'POST', body: JSON.stringify({ action: 'backups.verify', backupId: backup.id }) })
        if (!verification.ok) throw new Error(verification.error || 'Could not verify the backup.')
        verificationRequested = true
      }
    }
    if (backup?.phase === 'failed') throw new Error(backup.error || 'The backup failed.')
    const operation = reply.data.operation
    if (operation && operation.id === operationId && operation.phase === 'failed') throw new Error(operation.error || 'The backup failed.')
  }
  throw new Error('The backup has not finished. Check its saved status before starting another.')
}

export async function importDockerBackup(file: File): Promise<void> {
  if (file.size < 5 || file.size > 25 * 1024 ** 3) throw new Error('Choose a PostgreSQL custom backup up to 25 GiB.')
  if (new TextDecoder().decode(await file.slice(0, 5).arrayBuffer()) !== 'PGDMP') throw new Error('Choose a PostgreSQL custom-format backup, not a SQL script or other file.')
  const started = await api<Reply & { uploadId: string }>('/api/docker/backup-import', {
    method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream', 'X-Dst-Trusted-Backup': 'true', 'X-Dst-Backup-Filename': encodeURIComponent(file.name) },
  })
  if (!started.ok || !/^[a-f0-9]{32}$/.test(started.uploadId)) throw new Error(started.error || 'Refresh Database to check whether the import was recorded before retrying.')
  const deadline = Date.now() + 2 * 60 * 60 * 1000
  while (Date.now() < deadline) {
    const reply = await api<Reply>('/api/docker/setup')
    if (!reply.ok || !reply.data) throw new Error(reply.error || 'Could not read import progress. Refresh Database before retrying.')
    const backup = reply.data.backups.find(row => row.id === started.uploadId)
    if (backup?.phase === 'completed') return
    if (backup?.phase === 'failed') throw new Error(backup.error || 'Backup import failed. Existing backups and the world were preserved.')
    if (reply.data.operation?.id === started.data?.operation?.id && reply.data.operation?.phase === 'failed') throw new Error(reply.data.operation.error || 'Import needs review. Refresh Database before retrying.')
    await new Promise(resolve => window.setTimeout(resolve, 1000))
  }
  throw new Error('Import is still pending. Refresh Database to inspect its saved status before retrying.')
}

export async function verifyDockerBackup(path: string): Promise<void> {
  const initial = await api<Reply>('/api/docker/setup')
  const backup = initial.data?.backups.find(row => row.phase === 'completed' && '/backups/' + row.name === path)
  if (!initial.ok || !backup) throw new Error('Choose a completed backup from this installation.')
  const started = await api<Reply>('/api/docker/setup', { method: 'POST', body: JSON.stringify({ action: 'backups.verify', backupId: backup.id }) })
  if (!started.ok) throw new Error(started.error || 'Could not start restore verification. Start the database first.')
  const deadline = Date.now() + 2 * 60 * 60 * 1000
  while (Date.now() < deadline) {
    const reply = await api<Reply>('/api/docker/setup')
    if (!reply.ok || !reply.data) throw new Error(reply.error || 'Could not read restore verification progress.')
    const verification = reply.data.backups.find(row => row.id === backup.id)?.verification
    if (verification?.phase === 'completed') return
    if (verification?.phase === 'failed') throw new Error(verification.error || 'The restore rehearsal failed; the current world was preserved.')
    if (reply.data.operation?.id === started.data?.operation?.id && reply.data.operation?.phase === 'failed') throw new Error(reply.data.operation.error || 'Could not verify this backup.')
    await new Promise(resolve => window.setTimeout(resolve, 1000))
  }
  throw new Error('Restore verification is still pending. Refresh Database before retrying.')
}
