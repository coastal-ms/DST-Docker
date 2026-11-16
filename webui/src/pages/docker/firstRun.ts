import { api } from '../../api/client'
import type { SetupState } from './DockerSetup'

// Container lifecycle and credentials can change after setup. A stopped or
// damaged established world must retain access to its management/recovery UI.
export function setupComplete(state: SetupState): boolean {
  const prepared = new Set(state.services.filter(item => item.phase === 'prepared').map(item => item.component))
  return !!state.profile && state.partitionsPrepared
    && ['director', 'gateway', 'text-router'].every(name => prepared.has(name))
    && [...prepared].some(name => name.startsWith('game-'))
}

export async function readSetup(signal?: AbortSignal): Promise<SetupState> {
  const reply = await api<{ ok: boolean; data?: SetupState; error?: string }>('/api/docker/setup', { signal })
  if (!reply.ok || !reply.data) throw new Error(reply.error || 'Could not read setup progress.')
  return reply.data
}

export type WorldDetails = { name: string; region: string; address: string; gamePortBase: number; port: number; token: string }

export async function prepareFirstWorld(details: WorldDetails, update: (state: SetupState, label: string) => void, signal: AbortSignal) {
  let state = await readSetup(signal)
  const pause = () => new Promise<void>((resolve, reject) => {
    signal.throwIfAborted()
    const abort = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')) }
    const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve() }, 1500)
    signal.addEventListener('abort', abort, { once: true })
  })
  const wait = async (ready: () => boolean, label: string) => {
    const deadline = Date.now() + 15 * 60 * 1000
    while (!ready()) {
      if (Date.now() > deadline) throw new Error('Preparation is taking longer than expected. Check progress and continue when ready.')
      await pause()
      state = await readSetup(signal)
      update(state, label)
      if (state.startupRecoveryError) throw new Error(state.startupRecoveryError)
      if (['failed', 'interrupted'].includes(state.operation?.phase ?? '')) throw new Error(state.operation?.error || 'Preparation needs attention. Review the error before continuing.')
    }
  }
  const action = async (name: string, label: string, values: object = {}) => {
    signal.throwIfAborted()
    update(state, label)
    const reply = await api<{ ok: boolean; data?: SetupState; error?: string }>('/api/docker/setup', {
      method: 'POST', signal, body: JSON.stringify({ action: name, ...values }),
    })
    // An uncertain response ends this run. Never automatically replay a write.
    if (!reply.ok || !reply.data) throw new Error(reply.error || 'Could not confirm this step. Check progress before continuing.')
    state = reply.data
    await wait(() => state.operation?.phase !== 'running', label)
    if (['failed', 'interrupted'].includes(state.operation?.phase ?? '') && name !== 'credentials.save') throw new Error(state.operation?.error || 'Preparation failed.')
    update(state, label)
  }
  if (state.startupRecoveryError) throw new Error(state.startupRecoveryError)
  await wait(() => state.operation?.phase !== 'running', 'Finishing the current step')
  const failedPreparation = state.operation?.action === 'services.prepare'
    && ['failed', 'interrupted'].includes(state.operation.phase)
  // Prepared container records can exist even when the final helper failed.
  // An explicit Continue must retry that unfinished preparation, not claim success.
  if (setupComplete(state) && !failedPreparation) return state
  if (state.assets.state !== 'downloaded') throw new Error('The official game files are still downloading. Keep the installer open and continue when the download finishes.')
  if (!state.credentialsSaved) await action('credentials.save', 'Saving your service token', { token: details.token })
  if (!state.database) await action('database.create', 'Creating your server storage', { port: details.port })
  if (!['database-initialized', 'database-migrating', 'database-ready', 'database-migration-failed'].includes(state.phase)) {
    await wait(() => state.database?.state === 'running' && state.database.health === 'healthy', 'Waiting for your server storage')
    await action('database.initialize', 'Preparing your server storage')
  }
  if (['database-initialized', 'database-migration-failed'].includes(state.phase)) await action('database.migrate', 'Installing the game database')
  await wait(() => state.phase === 'database-ready', 'Installing the game database')
  if (!state.partitionsPrepared) await action('world.configure', 'Creating your world', {
    profile: { name: details.name.trim(), region: details.region, address: details.address.trim(), gamePortBase: details.gamePortBase },
  })
  // services.prepare also prepares connection services and safely reuses
  // previously prepared components. The manager rejects ambiguous attempts.
  await action('services.prepare', 'Preparing your world and initial maps')
  if (!setupComplete(state)) throw new Error('Your world is not ready yet. Check progress before continuing.')
  return state
}
