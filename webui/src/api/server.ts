// Server identity API — rename the battlegroup title shown in the in-game
// server browser / status pages (CRD spec.title). Restart-class on the server.
import { api } from './client'
import { completeDockerCommand } from './dockerCommand'

export interface RenameServerResult {
  ok: boolean
  oldName?: string
  newName?: string
  message?: string
}

export async function renameServer(name: string) {
  const result = await api<RenameServerResult & { operationId?: string }>('/api/server/name', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
  if (import.meta.env.VITE_DST_EDITION === 'docker' && result.ok) {
    if (!result.operationId) throw new Error('The server rename did not start.')
    await completeDockerCommand(result.operationId)
    return { ...result, message: `Server renamed to "${result.newName ?? name}".` }
  }
  return result
}
