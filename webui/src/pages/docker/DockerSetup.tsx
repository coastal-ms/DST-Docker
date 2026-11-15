import { useEffect, useState } from 'react'
import { api } from '../../api/client'

export type SetupState = {
  phase: string
  assets: { state: string; images: { archive: string; tags: string[] }[] }
  database: null | { name: string; port: number; state: string; health: string }
  credentialsSaved: boolean
  profile: null | { name: string; region: string; address: string; gamePortBase: number }
  partitionsPrepared: boolean
  connectionServices: { component: string; phase: string; state?: string; health?: string }[]
  plan: null | { maps: unknown[]; initialMemoryBytes: number }
  services: { component: string; phase: string; state?: string }[]
  desiredState: string
  operation: null | { action: string; phase: string; error?: string }
  startupRecoveryError?: string | null
}
type Reply = { ok: boolean; data?: SetupState; error?: string }

export default function DockerSetup() {
  const [state, setState] = useState<SetupState | null>(null)
  const [error, setError] = useState('')
  const [connectionError, setConnectionError] = useState('')
  const [tokenSavedFeedback, setTokenSavedFeedback] = useState(false)
  const [posting, setPosting] = useState(false)
  const busy = posting || state?.operation?.phase === 'running'
  const [port, setPort] = useState('18932')
  const [token, setToken] = useState('')
  const [worldName, setWorldName] = useState('Dune Server')
  const [region, setRegion] = useState('North America')
  const [address, setAddress] = useState('127.0.0.1')
  const [gamePortBase, setGamePortBase] = useState('7777')
  const [editingWorld, setEditingWorld] = useState(false)
  function editWorld() {
    if (state?.profile) {
      setWorldName(state.profile.name); setRegion(state.profile.region)
      setAddress(state.profile.address); setGamePortBase(String(state.profile.gamePortBase))
    }
    setEditingWorld(true)
  }
  const prepared = ['database-initialized','database-migrating','database-ready','database-migration-failed'].includes(state?.phase ?? '')
  const databaseHealth = state?.database && ['created', 'exited'].includes(state.database.state) ? 'Stopped' : state?.database?.state === 'restarting' ? 'Starting' : state?.database?.health
  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const result = await api<Reply>('/api/docker/setup')
        if (active) { if (result.ok && result.data) { setState(result.data); setConnectionError('') } else setConnectionError(result.error || 'Setup is unavailable.') }
      } catch { if (active) setConnectionError('Could not connect to setup. Retrying.') }
    }
    void load()
    const timer = window.setInterval(() => void load(), 10000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])
  async function perform(action: string) {
    setPosting(true); setError('')
    try {
      const result = await api<Reply>('/api/docker/setup', { method: 'POST', body: JSON.stringify({ action, port: Number(port), ...(action === 'credentials.save' ? { token } : {}), ...(action === 'world.configure' ? { profile: { name: worldName, region, address, gamePortBase: Number(gamePortBase) } } : {}) }) })
      if (!result.ok || !result.data) throw new Error(result.error || 'Setup action failed.')
      setState(result.data)
      if (action === 'credentials.save') { setToken(''); setTokenSavedFeedback(true) }
      if (action === 'world.configure') setEditingWorld(false)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Setup action failed.') }
    finally { setPosting(false) }
  }
  return <div className="dc-setup">
    {(error || connectionError || state?.operation?.error) && <div role="alert" className="dc-notice">{error || connectionError || state?.operation?.error}</div>}
    {state?.operation?.phase === 'running' && <div role="status" className="dc-notice">Working on your server…</div>}
    <section className="dc-setup-card"><div className="dc-eyebrow">01 · OFFICIAL GAME FILES</div><h2>Linux server package</h2><p>{state?.assets.state === 'downloaded' ? 'Downloaded and verified.' : 'Waiting for the official server package. Check the installer terminal for download progress or errors. This page updates automatically when the files are ready.'}</p><span className="dc-tag">{state?.assets.images.length ?? 0} container images identified</span></section>
    <section className="dc-setup-card"><div className="dc-eyebrow">02 · YOUR SERVER DATABASE</div><h2>Prepare separate storage</h2><p>Your Docker server gets its own database and persistent storage.</p>
      {!state?.database ? <><label>Local database port<input type="number" min={1024} max={65535} value={port} onChange={event => setPort(event.target.value)} /></label><button className="dc-action" disabled={busy || state?.assets.state !== 'downloaded'} onClick={() => void perform('database.create')}>{busy ? 'Creating…' : 'Create database'}</button></> : <><dl><dt>Container</dt><dd>{state.database.state}</dd><dt>Health</dt><dd>{databaseHealth}</dd><dt>Local port</dt><dd>{state.database.port}</dd></dl>{!prepared ? <button className="dc-action" disabled={busy || state.database.health !== 'healthy'} onClick={() => void perform('database.initialize')}>{busy ? 'Preparing…' : 'Prepare game database'}</button> : ['database-initialized','database-migration-failed'].includes(state.phase) ? <button className="dc-action" disabled={busy} onClick={() => void perform('database.migrate')}>{busy ? 'Starting…' : state.phase === 'database-migration-failed' ? 'Retry schema installation' : 'Install game schema'}</button> : <span className="dc-connected">{state.phase === 'database-ready' ? 'Game database ready.' : 'Installing game schema…'}</span>}</>}
    </section>
    <section className="dc-setup-card"><div className="dc-eyebrow">03 · WORLD SETTINGS</div><h2>Your world</h2>{state?.partitionsPrepared && !editingWorld ? <><dl><dt>Name</dt><dd>{state.profile?.name}</dd><dt>Region</dt><dd>{state.profile?.region}</dd><dt>Address</dt><dd>{state.profile?.address}</dd><dt>Game-port base</dt><dd>{state.profile?.gamePortBase}</dd></dl><button className="dc-action" onClick={editWorld}>Edit world settings</button></> : <><label>World name<input maxLength={50} value={worldName} onChange={event => setWorldName(event.target.value)} /></label><label>Region<select value={region} onChange={event => setRegion(event.target.value)}>{['Asia','Europe','North America','Oceania','South America'].map(item => <option key={item}>{item}</option>)}</select></label><label>Server address<input value={address} onChange={event => setAddress(event.target.value)} /></label><label>Game-port base<input type="number" min={1024} max={65535} value={gamePortBase} onChange={event => setGamePortBase(event.target.value)} /></label><button className="dc-action" disabled={busy || state?.phase !== 'database-ready'} onClick={() => void perform('world.configure')}>{busy ? 'Preparing…' : 'Prepare world layout'}</button></>}</section>
    <section className="dc-setup-card"><div className="dc-eyebrow">04 · FUNCOM CONNECTION</div><h2>Service token</h2><p>{state?.credentialsSaved ? 'A service token is saved locally.' : 'Required when the game services are ready to connect.'}</p><label>Funcom service token<input type="password" autoComplete="new-password" value={token} onChange={event => { setToken(event.target.value); setTokenSavedFeedback(false) }} /></label><button className="dc-action" disabled={busy || token.length < 20} onClick={() => void perform('credentials.save')}>Save token locally</button>{tokenSavedFeedback && <p role="status" className="dc-connected">Token saved locally.</p>}</section>
    <section className="dc-setup-card"><div className="dc-eyebrow">05 · CONNECTION SERVICES</div><h2>World connections</h2>{state?.connectionServices?.length ? <dl>{state.connectionServices.map(service => <div key={service.component}><dt>{service.component === 'rmq-admin' ? 'Administration' : 'Game connection'}</dt><dd>{service.health === 'healthy' ? 'Ready' : service.state || service.phase}</dd></div>)}</dl> : <p>Prepare the local connection services for your world.</p>}<button className="dc-action" disabled={busy || !state?.partitionsPrepared} onClick={() => void perform('connections.prepare')}>{busy ? 'Preparing…' : 'Prepare connections'}</button></section>
    <section className="dc-setup-card"><div className="dc-eyebrow">06 · GAME SERVICES</div><h2>Start your world</h2>{state?.services?.length ? <><dl>{state.services.map(service => <div key={service.component}><dt>{service.component === 'game-1' ? 'Hagga Basin' : service.component === 'game-2' ? 'Overmap' : service.component}</dt><dd>{service.state || service.phase}</dd></div>)}</dl><button className="dc-action" disabled={busy} onClick={() => void perform('services.start')}>Start world</button><button className="dc-action" disabled={busy} onClick={() => void perform('services.stop')}>Stop world</button></> : <><p>Prepare the director, gateway and initial maps.</p><button className="dc-action" disabled={busy || !state?.credentialsSaved || !state?.partitionsPrepared} onClick={() => void perform('services.prepare')}>{busy ? 'Preparing…' : 'Prepare game services'}</button></>}</section>
  </div>
}
