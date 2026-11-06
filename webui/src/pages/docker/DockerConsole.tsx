import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import './docker.css'
import DockerSetup from './DockerSetup'
import DockerBackups from './DockerBackups'

type Container = { name: string; image: string; state: string; status: string; component?: string; map?: string; managed?: boolean; memory: { usedBytes: number; limitBytes: number } | null }
type Observation = { available: boolean; stale?: boolean; observedAt?: number; error?: string; host?: { memoryBytes: number; cpus: number; engineVersion: string }; containers?: Container[] }
type View = 'overview' | 'memory' | 'services' | 'setup' | 'backups'
const gib = (bytes: number) => (bytes / 1024 ** 3).toFixed(1)
function nameOf(container: Container) {
  if (container.map === 'Survival_1') return 'Hagga Basin'
  if (container.map === 'Overmap') return 'Overmap'
  if (container.map === 'DeepDesert_1') return 'Deep Desert'
  if (container.map) return container.map.replaceAll('_', ' ')
  if (container.component) return container.component.replaceAll('-', ' ')
  if (/server-survival-1$/.test(container.name)) return 'Hagga Basin'
  if (/server-overmap$/.test(container.name)) return 'Overmap'
  if (/deepdesert/.test(container.name)) return 'Deep Desert'
  return container.name.replace(/^dune-/, '').replaceAll('-', ' ')
}

export default function DockerConsole() {
  const [view, setView] = useState<View>('overview')
  const [observation, setObservation] = useState<Observation | null>(null)
  const [error, setError] = useState('')
  const [updated, setUpdated] = useState(0)
  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const response = await api<{ docker: Observation }>('/api/status')
        if (active) { setObservation(response.docker); setError(''); setUpdated(Date.now()) }
      } catch { if (active) setError('Connection interrupted. Retrying automatically.') }
    }
    void load()
    const timer = window.setInterval(() => void load(), 10000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])
  const containers = observation?.containers ?? []
  const running = containers.filter(c => c.state === 'running')
  const maps = containers.filter(c => /^registry\.funcom\.com\/funcom\/self-hosting\/seabass-server:/.test(c.image))
  const used = running.reduce((sum, c) => sum + (c.memory?.usedBytes ?? 0), 0)
  const hostBytes = observation?.host?.memoryBytes ?? 0
  const fresh = observation?.available && !observation.stale && !error
  return <div className="docker-console" tabIndex={0} role="region" aria-label="DST Docker workspace">
    <aside className="dc-sidebar">
      <a className="dc-brand" href="/"><span className="dc-sigil">D</span><span>DUNE SERVER TOOL<small>DOCKER EDITION</small></span></a>
      <div className="dc-nav-label">YOUR SERVER</div>
      <nav aria-label="Docker workspaces">{(['overview', 'memory', 'services', 'backups', 'setup'] as const).map((item, i) => <button key={item} className={view === item ? 'active' : ''} onClick={() => setView(item)}><span aria-hidden="true">{['◈', '▥', '▦', '▣', '⚙'][i]}</span>{item[0].toUpperCase() + item.slice(1)}</button>)}</nav>
      <div className="dc-sidebar-foot"><span className="dc-dot" />Local Docker connection<small>Private development preview</small></div>
    </aside>
    <main className="dc-main">
      <header className="dc-topbar"><span>SELF-HOSTED / {view.toUpperCase()}</span><span className={fresh ? 'dc-connected' : 'dc-muted'}>{fresh ? '● Connected' : '○ Connecting'}</span></header>
      <section className="dc-content">
        <div className="dc-heading"><div><div className="dc-eyebrow">YOUR CORNER OF ARRAKIS</div><h1>{view === 'overview' ? 'Server overview' : view === 'memory' ? 'Memory, at a glance' : view === 'setup' ? 'Set up your server' : view === 'backups' ? 'Protect your world' : 'Running services'}</h1><p>{view === 'overview' ? 'One place to see your worlds and the resources behind them.' : view === 'memory' ? 'Actual container use beside each memory ceiling.' : view === 'setup' ? 'Prepare your independent Docker server.' : view === 'backups' ? 'Save database snapshots and verify them with a separate restore.' : 'The containers supporting your Dune server.'}</p></div><span className="dc-tag">LINUX · DOCKER</span></div>
        {view === 'setup' ? <DockerSetup /> : view === 'backups' ? <DockerBackups /> : <>
        {(error || !observation?.available || observation.stale) && <div role="status" className="dc-notice">{error || (observation?.stale ? 'These readings are stale. Waiting for a fresh observation.' : observation?.error || 'Connecting to Docker…')}</div>}
        <div className="dc-metrics">
          <article><span>RUNNING SERVICES</span><strong>{observation?.available ? running.length : '—'}<small> / {containers.length}</small></strong><p>Observed Funcom containers</p></article>
          <article><span>CONTAINER MEMORY</span><strong>{observation?.available ? gib(used) : '—'}<small> GiB</small></strong><p>Working set across running services</p></article>
          <article><span>DOCKER HOST MEMORY</span><strong>{hostBytes ? gib(hostBytes) : '—'}<small> GiB</small></strong><p>{observation?.host?.cpus ?? '—'} logical CPUs available</p></article>
        </div>
        {view !== 'services' && <section className="dc-section"><div className="dc-section-title"><h2>{view === 'memory' ? 'Map memory' : 'Your worlds'}</h2><span>{maps.length} observed</span></div>
          <div className="dc-worlds">{maps.map(c => <article className="dc-world" key={c.name}><div className="dc-world-art"><span>{/survival/.test(c.name) ? 'HAGGA' : /overmap/.test(c.name) ? 'OVERMAP' : 'ARRAKIS'}</span><div className="dc-world-orbit" /></div><div className="dc-world-body"><div className="dc-world-title"><h3>{nameOf(c)}</h3><span className="dc-state">{c.state}</span></div><p>{c.status}</p><div className="dc-memory-label"><span>Memory</span><strong>{c.memory ? `${gib(c.memory.usedBytes)} / ${gib(c.memory.limitBytes)} GiB` : 'Unavailable'}</strong></div><meter min={0} max={c.memory?.limitBytes || 1} value={c.memory?.usedBytes || 0} aria-label={`${nameOf(c)} memory`} /><small>Ceiling is a limit, not preallocated memory.</small></div></article>)}</div>
          {!maps.length && <div className="dc-empty">No game-map containers observed yet. Your existing server is unchanged.</div>}
        </section>}
        {view !== 'memory' && <section className="dc-section"><div className="dc-section-title"><h2>Service health</h2><span>Docker {observation?.host?.engineVersion || '—'}</span></div><div className="dc-table-wrap"><table><thead><tr><th>Service</th><th>State</th><th>Memory</th><th>Status</th></tr></thead><tbody>{containers.map(c => <tr key={c.name}><td>{nameOf(c)}</td><td><span className="dc-state">{c.state}</span></td><td>{c.memory ? `${gib(c.memory.usedBytes)} GiB` : '—'}</td><td>{c.status}</td></tr>)}</tbody></table></div></section>}
        <footer className="dc-footer"><span>Observation only · server controls are being built</span><span>{updated ? `Updated ${new Date(updated).toLocaleTimeString()}` : 'Waiting for first reading'}</span></footer>
        </>}
      </section>
    </main>
  </div>
}
