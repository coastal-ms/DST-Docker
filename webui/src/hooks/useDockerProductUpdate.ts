import { useSyncExternalStore } from 'react'
import { api } from '../api/client'

export interface DockerProductUpdate {
  supported: boolean
  currentVersion?: string
  latestVersion?: string
  available: boolean
  tag?: string
  commit?: string
  error?: string
  operation?: { id: string; phase: 'running' | 'completed' | 'failed'; message: string; toVersion?: string }
}

const listeners = new Set<() => void>()
let status: DockerProductUpdate | null = null
let inflight: Promise<DockerProductUpdate> | null = null
let lastChecked = 0
let timer: number | undefined
export function publishDockerProductUpdate(result: DockerProductUpdate) {
  status = result
  lastChecked = Date.now()
  listeners.forEach(listener => listener())
}
export function checkDockerProductUpdate(force = false): Promise<DockerProductUpdate> {
  if (inflight) return inflight
  inflight = api<DockerProductUpdate>(`/api/docker/product-update${force ? '?force=1' : ''}`)
    .then(result => { publishDockerProductUpdate(result); return result })
    .finally(() => { inflight = null })
  return inflight
}
function wake() {
  if (document.visibilityState !== 'hidden' && Date.now() - lastChecked >= 5 * 60 * 1000) {
    void checkDockerProductUpdate().catch(() => {})
  }
}
function subscribe(listener: () => void) {
  listeners.add(listener)
  if (listeners.size === 1) {
    void checkDockerProductUpdate().catch(() => {})
    timer = window.setInterval(() => { void checkDockerProductUpdate().catch(() => {}) }, 6 * 60 * 60 * 1000)
    window.addEventListener('focus', wake)
    document.addEventListener('visibilitychange', wake)
  }
  return () => {
    listeners.delete(listener)
    if (!listeners.size) {
      window.clearInterval(timer)
      window.removeEventListener('focus', wake)
      document.removeEventListener('visibilitychange', wake)
    }
  }
}
export function useDockerProductUpdate() {
  return useSyncExternalStore(subscribe, () => status, () => status)
}
