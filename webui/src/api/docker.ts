import { api } from './client'

type Backup = { id: string; phase: string; error?: string; verification?: { phase: string; error?: string } }
type State = { backups: Backup[]; operation?: { id: string; phase: string; error?: string } }
type Reply = { ok: boolean; data?: State; error?: string }

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
