import { api, authenticatedApiNavigation } from './client'

type Operation = { id: string; phase: string; error?: string; result?: { downloadId?: string; complete?: boolean } }

/** Follow the persisted operation identity; never replay an expired request. */
export async function completeDockerCommand(operationId: string): Promise<{ downloaded: boolean; complete: boolean }> {
  const deadline = Date.now() + 10 * 60 * 1000
  while (Date.now() < deadline) {
    await new Promise(resolve => window.setTimeout(resolve, 2000))
    const current = await api<{ state: { operation?: Operation } }>('/api/commands')
    const operation = current.state.operation
    if (operation?.id !== operationId) throw new Error('The server operation changed. Refresh server status.')
    if (operation.phase === 'failed' || operation.phase === 'interrupted') throw new Error(operation.error || 'Server operation failed.')
    if (operation.phase === 'completed') {
      const id = operation.result?.downloadId
      if (id) {
        if (!/^[a-f0-9]{32}$/.test(id)) throw new Error('The log download identity is invalid. Export it again.')
        const anchor = document.createElement('a')
        anchor.href = authenticatedApiNavigation(`/api/docker/log-exports/${id}`)
        anchor.download = 'DST-logs.zip'
        document.body.appendChild(anchor);anchor.click();anchor.remove()
      }
      return { downloaded: !!id, complete: operation.result?.complete !== false }
    }
  }
  throw new Error('The server operation is still running. Check server status.')
}
