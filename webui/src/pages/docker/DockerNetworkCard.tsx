import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, withOnlinePlayerGuard } from '../../api/client'
import { CollapsibleCard } from '../../components/CollapsibleCard'
import DockerLanSettings from './DockerLanSettings'
import DockerLoopbackSettings from './DockerLoopbackSettings'
import { ConfirmationModal } from '../../components/ConfirmationModal'

type Mode = 'private' | 'public'
type NetworkState = {
  profile: { address: string; gamePortBase: number } | null
  plan: { ports: { 'rmq-game': number } } | null
  desiredState: string
  operation: { id: string; action: string; phase: string; error?: string; stage?: string; targetAddress?: string; targetMode?: Mode; resume?: boolean } | null
  services: unknown[]
}
type Reply = { ok: boolean; data?: NetworkState; error?: string }
type PendingChange = { mode: Mode; address: string; expectedAddress: string; restart: boolean }
function modeFor(address: string): Mode {
  const octets = address.split('.').map(Number)
  return octets[0] === 10 || octets[0] === 127 || (octets[0] === 192 && octets[1] === 168) ||
    (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31) ? 'private' : 'public'
}

export default function DockerNetworkCard() {
  const [state, setState] = useState<NetworkState | null>(null)
  const [mode, setMode] = useState<Mode>('private')
  const [address, setAddress] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [posting, setPosting] = useState(false)
  const [confirmation, setConfirmation] = useState<PendingChange | null>(null)
  const [submitted, setSubmitted] = useState<string | null>(null)
  const submittedRef = useRef<string | null>(null)
  const initialized = useRef(false)
  const requestGeneration = useRef(0)
  const [detecting, setDetecting] = useState(false)
  const [dockerIp, setDockerIp] = useState('')
  const [forwardIp, setForwardIp] = useState('')
  const [networkMode, setNetworkMode] = useState('')
  const detectionVersion = useRef(0)
  const [detectedLoopbackIp, setDetectedLoopbackIp] = useState('')
  const [loopbackLookupAddress, setLoopbackLookupAddress] = useState<string | null>(null)
  const savedAddress = state?.profile?.address
  const savedPublicIp = savedAddress && modeFor(savedAddress) === 'public' ? savedAddress : ''
  const lookupAddress = loopbackLookupAddress ?? (savedPublicIp || detectedLoopbackIp)
  const candidate = lookupAddress.trim()
  const loopbackIp = /^\d{1,3}(\.\d{1,3}){3}$/.test(candidate) &&
    candidate.split('.').every(octet => Number(octet) <= 255) && modeFor(candidate) === 'public' ? candidate : ''
  useEffect(() => () => { detectionVersion.current++ }, [])
  useEffect(() => {
    if (!savedAddress || savedPublicIp || detectedLoopbackIp || loopbackLookupAddress !== null) return
    let active = true
    api<{ publicIp: string }>('/api/docker/network/public-ip').then(value => {
      if (active && value.publicIp) setDetectedLoopbackIp(value.publicIp)
    }).catch(() => {})
    return () => { active = false }
  }, [savedAddress, savedPublicIp, detectedLoopbackIp, loopbackLookupAddress])
  useEffect(() => {
    let active = true
    const timer = window.setTimeout(() => {
      api<{ dockerIp: string; routerForwardIp?: string; networkingMode?: string }>('/api/docker/network').then(value => {
        if (active && value.dockerIp) { setDockerIp(value.dockerIp); setForwardIp(value.routerForwardIp || value.dockerIp); setNetworkMode(value.networkingMode || '') }
      }).catch(() => {})
    }, 200)
    return () => { active = false; window.clearTimeout(timer) }
  }, [mode])
  async function detectPublicIp() {
    const version = ++detectionVersion.current
    setDetecting(true); setError(''); setMessage('')
    try {
      const result = await api<{ publicIp: string }>('/api/docker/network/public-ip')
      if (detectionVersion.current === version) setAddress(result.publicIp)
    } catch (e) {
      if (detectionVersion.current === version) setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (detectionVersion.current === version) setDetecting(false)
    }
  }
  function chooseMode(value: Mode) {
    detectionVersion.current++; setDetecting(false)
    setMode(value); setAddress(''); setError(''); setMessage('')
    if (value === 'public') void detectPublicIp()
  }
  useEffect(() => {
    let active = true
    let loading = false
    const load = async () => {
      if (loading) return
      loading = true
      const generation = requestGeneration.current
      try {
        const reply = await api<Reply>('/api/docker/setup')
        if (!reply.ok || !reply.data) throw new Error(reply.error || 'Network settings are unavailable.')
        if (!active || generation !== requestGeneration.current) return
        const value = reply.data
        const pending = submittedRef.current
        setState(value)
        if (!pending && value.operation?.action === 'network.set' && ['failed', 'interrupted'].includes(value.operation.phase)) {
          setError(value.operation.error || 'The network update failed. Check server status before retrying.')
        }
        if (!initialized.current && value.profile) {
          const operation = value.operation
          const target = operation?.action === 'network.set' && operation.phase === 'running' ? operation : null
          setAddress(target?.targetAddress ?? value.profile.address)
          setMode(target?.targetMode ?? modeFor(value.profile.address))
          initialized.current = true
        }
        if (pending && value.operation?.id !== pending) {
          submittedRef.current = null; setSubmitted(null)
          setError('The server operation changed. Review the current connection settings before retrying.')
        } else if (pending && value.operation?.id === pending && value.operation.phase !== 'running') {
          submittedRef.current = null
          setSubmitted(null)
          if (value.operation.phase !== 'completed') setError(value.operation.error || 'The network update was interrupted. Check server status before retrying.')
          else {
            setError(''); setMessage('Player connection settings applied.')
            if (value.profile) { setAddress(value.profile.address); setMode(modeFor(value.profile.address)) }
          }
        }
      } catch (e) { if (active && generation === requestGeneration.current) setError(e instanceof Error ? e.message : String(e)) }
      finally { loading = false }
    }
    void load()
    const timer = window.setInterval(() => void load(), 3000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])
  const busy = posting || !!submitted || state?.operation?.phase === 'running'
  useEffect(() => {
    if (!busy && mode === 'private' && dockerIp) setAddress(dockerIp)
  }, [busy, mode, dockerIp])
  const legacyPorts = !!state?.profile && (state.profile.gamePortBase !== 7777 || state.plan?.ports['rmq-game'] !== 31982)
  const changed = !!state?.profile && (address.trim() !== state.profile.address || legacyPorts)
  function apply(event: FormEvent) {
    event.preventDefault()
    if (!state?.profile || busy || !changed) return
    setConfirmation({ mode, address: address.trim(), expectedAddress: state.profile.address, restart: state.desiredState === 'running' })
  }
  async function confirmApply(change: PendingChange) {
    setConfirmation(null)
    if (!state?.profile || busy || state.profile.address !== change.expectedAddress || (state.desiredState === 'running') !== change.restart) {
      setError('The server state changed. Review the current settings and apply again.'); return
    }
    requestGeneration.current++
    setPosting(true); setError(''); setMessage('')
    try {
      const reply = await withOnlinePlayerGuard(force => api<Reply>(`/api/docker/setup${force ? '?force=1' : ''}`, { method: 'POST', body: JSON.stringify({
        action: 'network.set', mode: change.mode, address: change.address, expectedAddress: change.expectedAddress,
      }) }))
      if (!reply.ok || !reply.data) throw new Error(reply.error || 'Network settings could not be applied.')
      setState(reply.data)
      if (reply.data.operation?.phase === 'running') { submittedRef.current = reply.data.operation.id; setSubmitted(reply.data.operation.id) }
      else if (reply.data.operation?.phase === 'failed') throw new Error(reply.data.operation.error || 'Network update failed.')
      else setMessage('Player connection settings applied.')
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setPosting(false) }
  }
  return <CollapsibleCard id="docker-network" title="IP configurations" icon="Network" subtitle="Configure the Docker LAN address and private or public player access.">
    <DockerLanSettings />
    {state?.profile && <p className="mb-3 text-sm">Current address: <strong>{state.profile.address}</strong> · {modeFor(state.profile.address) === 'private' ? 'Private / LAN' : 'Public / External'}</p>}
    <form onSubmit={apply} className="space-y-4">
      {dockerIp && <div className="rounded border border-border p-3 text-sm"><p>Docker IP: <strong>{dockerIp}</strong></p>{mode === 'public' && <>
        <p>Forward router ports to <strong>{forwardIp}</strong>: TCP <strong>31982</strong> and UDP <strong>7777–7810</strong>.</p>
        {networkMode === 'nat' && <p className="mt-2 text-warning">WSL is using an internal NAT address. Select Own LAN address above for a direct LAN address to use in your router.</p>}
      </>}</div>}
      <label className="block text-sm">Player access<select className="block mt-1 rounded border border-border bg-surface p-2" value={mode} disabled={busy} onChange={e => chooseMode(e.target.value as Mode)}>
        <option value="private">Private / LAN</option><option value="public">Public / External</option>
      </select></label>
      <label className="block text-sm">{mode === 'public' ? 'Public IPv4 address' : 'LAN IPv4 address'}<input className="block mt-1 w-full rounded border border-border bg-surface p-2" required readOnly={mode === 'private'} value={address} disabled={busy} onChange={e => { detectionVersion.current++; setDetecting(false); setAddress(e.target.value) }} placeholder={mode === 'public' ? 'Your router’s public IPv4 address' : 'Detected Docker host address'} /></label>
      {mode === 'private' && <p className="text-sm text-text-muted">Private access uses the detected Docker address. Assign a different address in Docker LAN address above.</p>}
      {mode === 'public' && <button type="button" className="btn-secondary" disabled={busy || detecting} onClick={() => void detectPublicIp()}>{detecting ? 'Detecting public IP…' : 'Detect public IP'}</button>}
      <p className="text-sm text-text-muted">{mode === 'public' ? 'Outside players connect through this public address. Forward TCP 31982 and UDP 7777–7810 from your router to the Docker host.' : 'Players on your local network connect through the Docker host’s LAN address.'}</p>
      <p className="text-sm">Player ports: <strong>TCP 31982</strong> and <strong>UDP 7777–7810</strong>.</p>
      {legacyPorts && <p className="text-sm text-warning">Applying will also replace the old player ports (TCP {state?.plan?.ports['rmq-game'] ?? 'unknown'}, UDP starting at {state?.profile?.gamePortBase}) with the ports shown above.</p>}
      {state?.operation?.action === 'network.set' && state.operation.phase === 'running'
        ? <p role="status" className="text-sm text-text-muted">{state.operation.stage === 'reconfiguring' ? 'Updating advertised addresses and connection services…' : state.operation.stage === 'restarting' ? 'Starting the game server with the new address…' : 'Stopping maps cleanly before changing the address. This can take a few minutes…'}</p>
        : <p className="text-sm text-text-muted">{state?.desiredState === 'running' ? 'Applying restarts the game server and disconnects connected players.' : 'The game server will remain stopped after applying.'}</p>}
      {!state?.services.length && <p className="text-sm text-text-muted">Finish preparing your world in Server setup first.</p>}
      {error && <p role="alert" className="text-danger">{error}</p>}
      <button className="btn-primary" disabled={busy || detecting || !state?.services.length || !changed} type="submit">{busy ? 'Applying…' : 'Apply player connections'}</button>
      {message && <p role="status" className="text-success">{message}</p>}
    </form>
    <div className="mt-4 space-y-3">
      {loopbackIp ? <DockerLoopbackSettings key={loopbackIp} publicIp={loopbackIp} dockerIp={dockerIp} sharedLan={networkMode === 'mirrored'} /> : <h3 className="font-semibold">Same-PC public-IP loopback</h3>}
      <label className="block text-sm">Public IPv4 address for loopback
        <input className="block mt-1 rounded border border-border bg-surface p-2" value={lookupAddress} onChange={event => setLoopbackLookupAddress(event.target.value)} />
      </label>
      {!loopbackIp && <p className="text-sm text-text-muted">Enter the public IPv4 address used by the route to see its current target.</p>}
    </div>
    {confirmation && <ConfirmationModal
      title="Apply player access changes?"
      description={`${confirmation.mode === 'public' ? 'Public / External' : 'Private / LAN'} will use ${confirmation.address}. ${confirmation.restart ? 'This will stop the maps, update their connection settings, and restart the game server. Connected players will be disconnected.' : 'The game server is stopped and will remain stopped after these settings are applied.'}`}
      confirmLabel={confirmation.restart ? 'Apply and restart server' : 'Apply settings'}
      onCancel={() => setConfirmation(null)}
      onConfirm={() => void confirmApply(confirmation)}
    />}
  </CollapsibleCard>
}
