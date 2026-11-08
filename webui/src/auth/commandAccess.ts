import type { PortalAccountRole } from './portalAccess'

const REMOTE_ALLOWED = new Set(['startup', 'start', 'restart', 'start-vm', 'reboot', 'apply-inis'])

export function canAccessCommand(
  commandName: string,
  localViewer: boolean,
  role: PortalAccountRole,
  docker = false,
) {
  if (role === 'player') return false
  if (docker && role === 'owner' && ['start', 'stop', 'restart', 'apply-inis', 'update', 'logs-export', 'operator-logs-export'].includes(commandName)) return true
  return (localViewer && !docker) ||
    REMOTE_ALLOWED.has(commandName) ||
    ((role === 'owner' || role === 'admin') && ['update', 'update-with-tanks'].includes(commandName))
}
