import { usePortalAuth } from './PortalAuthGate'
import { isLocalViewer } from '../util/viewer'

export type PortalAccountRole = 'owner' | 'admin' | 'player' | null

export function resolvePortalAccess(
  localViewer: boolean,
  accountLoginEnabled: boolean,
  role: PortalAccountRole,
  dockerEdition = false,
) {
  return {
    isPlayer: accountLoginEnabled && role === 'player',
    canAccessOwnerSurfaces: localViewer || !accountLoginEnabled || role === 'owner',
    canAccessServerUpdates: role !== 'player' && (localViewer || role === 'owner' || role === 'admin'),
    canAccessSetup: localViewer || (dockerEdition && (!accountLoginEnabled || role === 'owner')),
  }
}

export function usePortalAccess() {
  const portalAuth = usePortalAuth()
  const role = portalAuth?.status.account?.role ?? null
  return resolvePortalAccess(
    isLocalViewer(),
    portalAuth?.status.accountLoginEnabled === true,
    role,
    import.meta.env.VITE_DST_EDITION === 'docker',
  )
}
