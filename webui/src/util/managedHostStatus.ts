import type { StatusSnapshot } from '../api/types'

// Shared screens use vm for host availability. Keep the wire snapshot truthful
// and adapt both polled and freshly requested snapshots at the same boundary.
export function withManagedHost(snapshot: StatusSnapshot): StatusSnapshot {
  if (snapshot.hostingBackend !== 'docker') return snapshot
  return {
    ...snapshot,
    vm: snapshot.host ?? { ...snapshot.vm, exists: false, running: false, state: 'Unavailable' },
  }
}
