import { useEffect, useId, useRef, useState } from 'react'
import { useApi } from '../../hooks/useApi'
import { Icon } from '../../components/Icon'

type Operation = { id: string; phase: string; message?: string; error?: string }
type Progress = {
  available: boolean
  operationId: string
  build?: string
  label: string
  status: 'running' | 'completed' | 'failed'
  running: boolean
  startedAt?: number
  error?: string | null
  events: { label: string; at: number }[]
  output: { name: string; text?: string; error?: string; truncated?: boolean }[]
}

function Output({ text }: { text: string }) {
  const element = useRef<HTMLPreElement>(null)
  const following = useRef(true)
  useEffect(() => {
    if (following.current && element.current) element.current.scrollTop = element.current.scrollHeight
  }, [text])
  return <pre ref={element} onScroll={() => {
    const node = element.current
    if (node) following.current = node.scrollHeight - node.scrollTop - node.clientHeight < 30
  }} className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-black/30 p-3 text-xs font-mono text-text-muted">{text}</pre>
}

export function DockerUpdateProgress({ operation }: { operation?: Operation }) {
  const [expanded, setExpanded] = useState(false)
  const [follow, setFollow] = useState(operation?.phase === 'running')
  const id = useId()
  const query = new URLSearchParams({ output: expanded ? '1' : '0' })
  if (operation?.id) query.set('operationId', operation.id)
  const progress = useApi<Progress>('/api/docker/update-progress?' + query.toString(), {
    intervalMs: expanded && follow ? 2500 : 0,
  })
  useEffect(() => {
    void progress.refresh()
  }, [operation?.id, operation?.phase, operation?.message, progress.refresh])
  useEffect(() => {
    setFollow(progress.data?.running ?? operation?.phase === 'running')
  }, [progress.data?.running, operation?.phase])
  const data = progress.data
  if (!data?.available && !operation && !progress.error) return null
  const running = operation?.phase === 'running' || data?.running
  const failed = !running && (data?.status === 'failed' || ['failed', 'interrupted'].includes(operation?.phase ?? ''))
  const label = running && !data?.running ? operation?.message || 'Updating server' : data?.label || (operation?.phase === 'completed' ? 'Update complete' : 'Server update')
  return <section className={`card p-3 mb-4 text-sm ${failed ? 'border-danger/40' : ''}`} aria-label="Server update status">
    <div className="flex flex-wrap items-center gap-2">
      <Icon name={running ? 'RefreshCw' : failed ? 'AlertCircle' : 'CheckCircle2'} size={14} className={running ? 'animate-spin' : ''} />
      <span role="status" aria-label="Server update status" className="flex-1">{label}</span>
      <button type="button" className="text-accent underline underline-offset-4" aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded(value => !value)}>
        {expanded ? 'Hide details' : 'Details'}
      </button>
    </div>
    {failed && (data?.error || operation?.error) && <p role="alert" className="mt-2 text-danger">{data?.error || operation?.error}</p>}
    {progress.error && <p role="alert" className="mt-2 text-danger">Progress could not be refreshed. {progress.error}</p>}
    {expanded && <div id={id} role="region" aria-label="Server update details" className="mt-4 space-y-3 border-t border-border pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-text-muted">
        <span>{data?.build ? `Server build ${data.build}` : 'Server update'}{data?.startedAt ? ` · Started ${new Date(data.startedAt * 1000).toLocaleTimeString()}` : ''}</span>
        <button type="button" className="btn btn-secondary text-xs" onClick={() => void progress.refresh()}>Refresh details</button>
      </div>
      {data?.events && data.events.length > 0 && <ol className="max-h-32 overflow-auto space-y-1 text-xs text-text-muted">
        {data.events.map((event, index) => <li key={`${event.at}-${index}`}>{new Date(event.at * 1000).toLocaleTimeString()} — {event.label}</li>)}
      </ol>}
      {progress.loading && !data?.output?.length && <p className="text-text-muted">Loading update output…</p>}
      {data?.output?.map(output => <div key={output.name}>
        <h3 className="mb-1 text-xs font-semibold">{output.name}</h3>
        {output.error ? <p className="text-xs text-text-muted">{output.error}</p> : <Output text={output.text || 'Waiting for output…'} />}
        {output.truncated && <p className="mt-1 text-xs text-text-muted">Showing recent output.</p>}
      </div>)}
      {!progress.loading && !data?.output?.length && <p className="text-text-muted">No retained output is available for this update.</p>}
    </div>}
  </section>
}
