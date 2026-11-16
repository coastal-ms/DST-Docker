import { useState } from 'react'
import { Link } from '../router'
import { useDockerProductUpdate } from '../hooks/useDockerProductUpdate'
import { Icon } from './Icon'

const DISMISS_KEY = 'dune.docker.update.dismissed'
export function DockerUpdateBanner() {
  const data = useDockerProductUpdate()
  const [dismissed, setDismissed] = useState<string | null>(null)
  const version = data?.latestVersion
  if (!data?.available || !version || data.error || data.operation?.phase === 'running') return null
  if (dismissed === version || sessionStorage.getItem(DISMISS_KEY) === version) return null
  return <div className="shrink-0 border-b border-amber-400/30 bg-amber-400/10 px-5 py-2 text-sm text-amber-100 flex items-center gap-3">
    <Icon name="Download" size={16} className="text-amber-300 shrink-0" />
    <div className="flex-1 min-w-0"><strong className="font-semibold">DST Docker update available:</strong>{' '}
      <span className="text-amber-50">{version}</span>{' '}
      <span className="text-amber-200/70">(you're on {data.currentVersion})</span>
    </div>
    <Link to="/settings?section=settings.docker-updates" className="px-3 py-1 rounded-md bg-amber-400 text-amber-950 font-semibold text-xs hover:bg-amber-300">View update</Link>
    <button type="button" className="px-2 py-1 rounded-md text-amber-200 hover:text-white text-xs" title="Dismiss for this session"
      onClick={() => { sessionStorage.setItem(DISMISS_KEY, version); setDismissed(version) }}>Later</button>
  </div>
}
