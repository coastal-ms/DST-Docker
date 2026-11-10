// Database API — typed wrappers around /api/db/*
import { api, withOnlinePlayerGuard } from './client'
import type {
  DbInfo,
  SqlResult,
  BackupSchedule,
  BackupHistory,
  BackupDumpPodList,
  BackupDumpPodPruneResult,
} from './types'

export function getDbInfo() {
  return api<DbInfo>('/api/db/info')
}

export function runSql(opts: {
  sql: string
  readOnly?: boolean
  maxRows?: number
  timeoutSec?: number
}) {
  return api<SqlResult>('/api/db/query', {
    method: 'POST',
    body: JSON.stringify({
      sql:        opts.sql,
      readOnly:   opts.readOnly ?? true,
      maxRows:    opts.maxRows ?? 1000,
      timeoutSec: opts.timeoutSec ?? 30,
    }),
  })
}

export function getBackupSchedule() {
  return api<BackupSchedule>('/api/db/backup-schedule')
}

export function putBackupSchedule(opts: {
  preset: string
  keepLast: number
  keepLastPods?: number
  keepDaysPods?: number
}) {
  return api<BackupSchedule>('/api/db/backup-schedule', {
    method: 'PUT',
    body: JSON.stringify({
      preset:       opts.preset,
      keepLast:     opts.keepLast,
      keepLastPods: opts.keepLastPods,
      keepDaysPods: opts.keepDaysPods,
    }),
  })
}

export function getBackupHistory(opts: { recent?: number; logLines?: number } = {}) {
  const params = new URLSearchParams()
  if (opts.recent   != null) params.set('recent',   String(opts.recent))
  if (opts.logLines != null) params.set('logLines', String(opts.logLines))
  const qs = params.toString()
  return api<BackupHistory>(`/api/db/backup-history${qs ? `?${qs}` : ''}`)
}

export type BackupTransferResult = {
  ok: boolean
  path?: string
  remotePath?: string
  sizeBytes?: number
  message?: string
  error?: string
}

export function downloadBackup(opts: { vmPath: string; localPath: string }) {
  return api<BackupTransferResult>('/api/db/backup-download', {
    method: 'POST',
    body: JSON.stringify({ vmPath: opts.vmPath, localPath: opts.localPath }),
  })
}

export function uploadBackup(opts: { localPath: string }) {
  return api<BackupTransferResult>('/api/db/backup-upload', {
    method: 'POST',
    body: JSON.stringify({ localPath: opts.localPath }),
  })
}

export type BackupDeleteResult = {
  ok: boolean
  deleted: string[]
  failed: { path: string; reason: string }[]
  message?: string
  error?: string
  pending?: boolean
}

export async function deleteBackups(opts: { paths: string[] }) {
  const result = await api<BackupDeleteResult>('/api/db/backup-delete', {
    method: 'POST',
    body: JSON.stringify({ paths: opts.paths }),
  })
  if (import.meta.env.VITE_DST_EDITION === 'docker' && result.pending) {
    const { waitDockerBackupCleanup } = await import('./docker')
    await waitDockerBackupCleanup()
    return { ...result, pending: false, deleted: opts.paths, message: `Deleted ${opts.paths.length} backup file(s).` }
  }
  return result
}

export function getBackupDumpPods() {
  return api<BackupDumpPodList>('/api/db/backup-dump-pods')
}

export function pruneBackupDumpPods(opts: { keepLast: number; keepDays: number }) {
  return api<BackupDumpPodPruneResult>('/api/db/prune-backup-dump-pods', {
    method: 'POST',
    body: JSON.stringify({ keepLast: opts.keepLast, keepDays: opts.keepDays }),
  })
}

// Local backup mirror — copies each new VM backup into a user-chosen folder.
// Copy-only: the mirror never deletes local files (VM auto-purge is scoped
// to the VM only).
export type BackupMirrorState = {
  enabled: boolean
  folder: string
  lastMirroredAt: string
  lastError: string
  lastCopiedCount: number
}

export type BackupMirrorSyncResult = BackupMirrorState & {
  ok: boolean
  skipped?: boolean
  reason?: string
  vmFileCount?: number
  copied?: string[]
  copiedCount?: number
  failed?: { name: string; error: string }[]
  error?: string
}

export function getBackupMirror() {
  return api<BackupMirrorState>('/api/db/backup-mirror')
}

export function setBackupMirror(opts: { enabled?: boolean; folder?: string }) {
  return api<BackupMirrorState & { ok: boolean }>('/api/db/backup-mirror', {
    method: 'POST',
    body: JSON.stringify(opts),
  })
}

export function openBackupMirrorFolder(opts: { folder?: string } = {}) {
  return api<{ ok: boolean; folder: string }>('/api/db/backup-mirror/open', {
    method: 'POST',
    body: JSON.stringify(opts),
  })
}

export function syncBackupMirror() {
  return api<BackupMirrorSyncResult>('/api/db/backup-mirror/sync', {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export type WorldRestartStep = {
  id: string
  label: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'warning'
  detail?: string
}

export type WorldRestartStatus = {
  phase: string
  running: boolean
  operation?: 'restart' | 'rollback'
  world?: string
  backupPath?: string
  rollbackAvailable: boolean
  recoveryRequired?: boolean
  researchRecoveryRequired?: boolean
  researchRecoveryRunning?: boolean
  researchRecoveryBackupPath?: string
  automaticRollback?: boolean
  error?: string
  steps: WorldRestartStep[]
}

export type WorldRestartResearchMismatch = {
  characterName: string
  accountId: number
  funcomId: string
  itemKey: string
  baseRecipeId: string
  groupKey: string
}

export type WorldRestartResearchAudit = {
  available: boolean
  message: string
  capturedCharacters: number
  rehydratedCharacters: number
  pendingCharacters: string[]
  mismatches: WorldRestartResearchMismatch[]
}

export type WorldRestartResearchRecovery = {
  ok: boolean
  characterName: string
  funcomId: string
  itemKeys: string[]
  backupPath?: string
  backupSizeBytes?: number
  message: string
}

export function getWorldRestartStatus() {
  if (import.meta.env.VITE_DST_EDITION === 'docker') return getDockerWorldRestartStatus()
  return api<WorldRestartStatus>('/api/db/world-restart/status')
}

async function dockerWorldAction<T>(action: string, values: Record<string, unknown> = {}): Promise<T> {
  const reply = await api<{ ok: boolean; error?: string; data?: T }>('/api/docker/setup', { method: 'POST', body: JSON.stringify({ action, ...values }) })
  if (!reply.ok || !reply.data) throw new Error(reply.error || 'Docker World Restart is unavailable.')
  return reply.data
}

async function getDockerWorldRestartStatus() {
  const reply = await api<{ ok: boolean; error?: string; data?: { worldRestart: WorldRestartStatus } }>('/api/docker/setup')
  if (!reply.ok || !reply.data?.worldRestart) throw new Error(reply.error || 'Docker World Restart status is unavailable.')
  return reply.data.worldRestart
}

export async function resumeDockerWorldRestart() {
  await dockerWorldAction('world-restart.recover')
}

export function startWorldRestart(confirm: string) {
  if (import.meta.env.VITE_DST_EDITION === 'docker') return dockerWorldAction('world-restart.apply', { confirmation: confirm }).then(() => ({ ok: true, running: true, operation: 'restart' }))
  return withOnlinePlayerGuard(force =>
    api<{ ok: boolean; running: boolean; operation: string }>(
      `/api/db/world-restart${force ? '?force=true' : ''}`,
      { method: 'POST', body: JSON.stringify({ confirm }) },
    ),
  )
}

export function rollbackWorldRestart(confirm: string) {
  if (import.meta.env.VITE_DST_EDITION === 'docker') return dockerWorldAction('world-restart.rollback', { confirmation: confirm }).then(() => ({ ok: true, running: true, operation: 'rollback' }))
  return withOnlinePlayerGuard(force =>
    api<{ ok: boolean; running: boolean; operation: string }>(
      `/api/db/world-restart/rollback${force ? '?force=true' : ''}`,
      { method: 'POST', body: JSON.stringify({ confirm }) },
    ),
  )
}

export function getWorldRestartResearchAudit() {
  if (import.meta.env.VITE_DST_EDITION === 'docker') return dockerWorldAction<WorldRestartResearchAudit>('world-restart.research-audit')
  return api<WorldRestartResearchAudit>('/api/db/world-restart/research-audit')
}

export function recoverWorldRestartResearch(opts: {
  characterName: string
  funcomId: string
  itemKeys: string[]
  confirm: string
}) {
  if (import.meta.env.VITE_DST_EDITION === 'docker') return dockerWorldAction('world-restart.research', { confirmation: opts.confirm, characterName: opts.characterName, funcomId: opts.funcomId, itemKeys: opts.itemKeys }).then(() => ({ ok: true, characterName: opts.characterName, funcomId: opts.funcomId, itemKeys: opts.itemKeys, message: 'Research recovery started. Progress continues in Docker; keep players offline until it finishes.' }))
  return withOnlinePlayerGuard(force =>
    api<WorldRestartResearchRecovery>(
      `/api/db/world-restart/research-recover${force ? '?force=true' : ''}`,
      { method: 'POST', body: JSON.stringify(opts) },
    ),
  )
}

export function rollbackWorldRestartResearch(confirm: string) {
  if (import.meta.env.VITE_DST_EDITION === 'docker') {
    if (confirm !== 'ROLL BACK RESEARCH RECOVERY') return Promise.reject(new Error('Type ROLL BACK RESEARCH RECOVERY exactly.'))
    return dockerWorldAction('world-restart.research-recover').then(() => ({ ok: true, backupPath: '', message: 'Research recovery resumed. Keep players offline until it finishes.' }))
  }
  return withOnlinePlayerGuard(force =>
    api<{ ok: boolean; backupPath: string; message: string }>(
      `/api/db/world-restart/research-rollback${force ? '?force=true' : ''}`,
      { method: 'POST', body: JSON.stringify({ confirm }) },
    ),
  )
}
