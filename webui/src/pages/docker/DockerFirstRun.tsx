import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate } from '../../router'
import { prepareFirstWorld, readSetup, setupComplete } from './firstRun'
import type { SetupState } from './DockerSetup'
import './firstRun.css'

export default function DockerFirstRun({ children, canSetup = true }: { children: ReactNode; canSetup?: boolean }) {
  const [initial, setInitial] = useState<SetupState | null>(null)
  const [error, setError] = useState('')
  const [entered, setEntered] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const navigate = useNavigate()
  useEffect(() => {
    const controller = new AbortController()
    void readSetup(controller.signal).then(state => {
      setInitial(state); setError('')
      if (canSetup && !setupComplete(state)) navigate('/setup', { replace: true })
    }).catch(caught => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Setup is unavailable.') })
    return () => controller.abort()
  }, [attempt, canSetup, navigate])
  if (entered || (initial && setupComplete(initial))) return <>{children}</>
  if (!initial) return <SetupFrame><h1>Welcome to DST Docker</h1>{error ? <><p role="alert">{error}</p><button onClick={() => { setError(''); setAttempt(value => value + 1) }}>Try again</button></> : <p role="status">Checking your server setup…</p>}</SetupFrame>
  if (!canSetup) return <SetupFrame><h1>Your server needs setup</h1><p>The owner needs to finish setting up this server before the management portal is available.</p><button onClick={() => setAttempt(value => value + 1)}>Check again</button></SetupFrame>
  return <FirstWorld initial={initial} onFinish={() => { navigate('/', { replace: true }); setEntered(true) }} />
}

const steps = ['Welcome', 'Installation check', 'Server identity', 'Funcom token', 'Ports', 'Review', 'Prepare server', 'Finish']

function SetupFrame({ children, step, onStep, locked = false }: {
  children: ReactNode; step?: number; onStep?: (step: number) => void; locked?: boolean
}) {
  return <main className="first-run">
    <header className="first-run-banner">
      <div className="first-run-brand"><img src="/logo.png" alt="" /><span>DST <strong>Docker</strong></span></div>
      <div className="first-run-banner-copy"><span>YOUR SERVER. YOUR WORLD.</span><p>Your journey starts here.</p></div>
    </header>
    <div className={`first-run-layout${step === undefined ? ' first-run-loading' : ''}`}>
      {step !== undefined && <nav className="first-run-sidebar" aria-label="Setup steps"><ol>{steps.map((title, index) => <li key={title}>
        <button type="button" aria-current={step === index ? 'step' : undefined} disabled={locked || index > Math.min(step, 5) || step === 7} onClick={() => onStep?.(index)}>
          <span>{index + 1}.</span> {title}{index < step && <small aria-label="Completed">✓</small>}
        </button>
      </li>)}</ol></nav>}
      <section className="first-run-card" aria-labelledby="first-run-title">{children}</section>
    </div>
    <footer>DST Docker · Dune Server Tool</footer>
  </main>
}

function FirstWorld({ initial, onFinish }: { initial: SetupState; onFinish: () => void }) {
  const [state, setState] = useState(initial)
  const [name, setName] = useState(initial.profile?.name ?? 'Dune Server')
  const [region, setRegion] = useState(initial.profile?.region ?? 'North America')
  const [address, setAddress] = useState(initial.profile?.address ?? '')
  const [gamePort, setGamePort] = useState(String(initial.profile?.gamePortBase ?? 7777))
  const [port, setPort] = useState(String(initial.database?.port ?? 18932))
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState(initial.operation?.phase === 'running' ? 6 : 0)
  const [label, setLabel] = useState('')
  const [error, setError] = useState('')
  const controller = useRef<AbortController | null>(null)
  const locked = useRef(false)
  useEffect(() => () => controller.current?.abort(), [])
  useEffect(() => { document.getElementById('first-run-title')?.focus() }, [step])
  // Observing progress never starts or retries server operations.
  useEffect(() => {
    if (busy || step === 7) return
    const polling = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const refresh = async () => {
      try { const current = await readSetup(polling.signal); if (!polling.signal.aborted) setState(current) }
      catch (caught) { if (!polling.signal.aborted) setError(caught instanceof Error ? caught.message : 'Could not check progress.') }
      if (!polling.signal.aborted) timer = setTimeout(() => void refresh(), 5000)
    }
    timer = setTimeout(() => void refresh(), 5000)
    return () => { polling.abort(); clearTimeout(timer) }
  }, [busy, step])
  function goTo(next: number) {
    setStep(next)
  }
  async function prepare(event: FormEvent) {
    event.preventDefault()
    if (locked.current) return
    locked.current = true
    setBusy(true); setError(''); goTo(6)
    controller.current = new AbortController()
    try {
      const final = await prepareFirstWorld({ name, region, address, gamePortBase: Number(gamePort), port: Number(port), token }, (current, message) => { setState(current); setLabel(message); if (current.credentialsSaved) setToken('') }, controller.current.signal)
      setState(final); setToken(''); goTo(7)
    } catch (caught) { if (!controller.current.signal.aborted) setError(caught instanceof Error ? caught.message : 'Setup could not finish.') }
    finally { locked.current = false; setBusy(false) }
  }
  const downloading = state.assets.state !== 'downloaded'
  const stages = [
    { title: 'Game files', done: !downloading },
    { title: 'Server storage', done: state.phase === 'database-ready' },
    { title: 'Your world', done: state.partitionsPrepared },
    { title: 'Initial maps', done: setupComplete(state) },
  ]
  const running = busy || state.operation?.phase === 'running'
  const headings = ['Welcome to DST Docker', 'Check your installation', 'Give your world an identity', 'Connect to Funcom', 'Choose your ports', 'Review your server', 'Preparing your server', 'Your world is ready']
  function next(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (step === 5 || step === 6) { void prepare(event); return }
    goTo(step + 1)
  }
  return <SetupFrame step={step} onStep={goTo} locked={running}>
    <div className="first-run-eyebrow">STEP {step + 1} OF {steps.length} · {steps[step].toUpperCase()}</div>
    <h1 id="first-run-title" tabIndex={-1}>{headings[step]}</h1>
    {(error || state.operation?.error) && <div className="first-run-error" role="alert">{error || state.operation?.error}<p>Your saved server progress is kept. Review the message before continuing.</p></div>}
    <form onSubmit={next}>
      <div className="first-run-stage" key={step}>
        {step === 0 && <>
          <p>Run and manage your Dune: Awakening server from your browser. We’ll guide you through the first setup, then open your management portal.</p>
          <ul className="first-run-intro"><li>Choose your server identity and connection address.</li><li>Add your Funcom self-host service token.</li><li>Review your settings, then let DST prepare your world.</li></ul>
          <h2>Set up this host</h2>
          <div className="first-run-choice"><span className="first-run-choice-icon" aria-hidden="true">▤</span><div><h3>{state.database ? 'Continue your server setup' : 'Deploy a new server'}</h3><p>{state.database ? 'Continue from your saved progress. Existing server storage and world details are preserved.' : 'Create a fresh world with its own database and initial maps.'}</p></div><span className="first-run-selected" aria-label="Selected">✓</span></div>
          <p className="first-run-hint">Docker and the runtime location were prepared by the installer. This wizard completes your game-server setup.</p>
        </>}
        {step === 1 && <>
          <p>Your management portal is connected. The official game files must finish downloading before server preparation begins.</p>
          <dl className="first-run-checks"><div><dt>Management connection</dt><dd>Connected</dd></div><div><dt>Official game files</dt><dd>{downloading ? 'Downloading…' : 'Downloaded and verified'}</dd></div><div><dt>Server storage</dt><dd>{state.database ? 'Existing storage found' : 'Will be created during setup'}</dd></div></dl>
          <p className="first-run-hint" role="status">{downloading ? 'Keep the installer terminal open. You can enter your settings while the download continues; this status updates automatically.' : 'You’re ready to continue. DST will prepare your game services after you review the settings.'}</p>
        </>}
        {step === 2 && <>
          <p>Choose how your world appears and the address your players will use to connect.</p>
          <fieldset disabled={state.partitionsPrepared}>
            <label>World name<input required maxLength={50} pattern=".*\S.*" value={name} onChange={event => setName(event.target.value)} /></label>
            <div className="first-run-fields"><label>Region<select value={region} onChange={event => setRegion(event.target.value)}>{['Asia', 'Europe', 'North America', 'Oceania', 'South America'].map(item => <option key={item}>{item}</option>)}</select></label>
              <label>Server address<input aria-label="Server address" aria-describedby="setup-address-help" required pattern=".*\S.*" placeholder="Public IP address or hostname" value={address} onChange={event => setAddress(event.target.value)} /><small id="setup-address-help">Use the address your players can reach.</small></label></div>
          </fieldset>
          {state.partitionsPrepared && <p className="first-run-saved">✓ Your saved world details will be kept.</p>}
        </>}
        {step === 3 && <>
          <p>Your Funcom self-host service token connects this server to the game services.</p>
          {state.credentialsSaved ? <p className="first-run-saved">✓ Your Funcom service token is saved on this host.</p> : <label>Funcom service token<textarea aria-label="Funcom service token" aria-describedby="setup-token-help" required minLength={20} maxLength={8192} autoComplete="off" spellCheck={false} rows={5} value={token} onChange={event => setToken(event.target.value)} /><small id="setup-token-help">Paste your self-host service token from Funcom. DST saves it on your Docker host when you begin preparation.</small></label>}
        </>}
        {step === 4 && <>
          <p>Keep the defaults for a standard installation, or choose ports for this server.</p>
          <div className="first-run-fields"><label>Local database port<input type="number" required min={1024} max={65535} disabled={!!state.database} value={port} onChange={event => setPort(event.target.value)} /></label><label>Game port base<input type="number" required min={1024} max={65535} disabled={state.partitionsPrepared} value={gamePort} onChange={event => setGamePort(event.target.value)} /></label></div>
          <p className="first-run-hint">Existing storage keeps its current database port. Port forwarding and firewall rules remain under your control.</p>
        </>}
        {step === 5 && <>
          <p>Check your settings before preparing the server. You can go back to change any unfinished step.</p>
          <dl className="first-run-review">{[
            ['World name', state.profile?.name ?? name.trim()], ['Region', state.profile?.region ?? region],
            ['Server address', state.profile?.address ?? address.trim()], ['Funcom token', state.credentialsSaved ? 'Saved on this host' : 'Provided · saved when setup begins'],
            ['Local database port', String(state.database?.port ?? port)], ['Game port base', String(state.profile?.gamePortBase ?? gamePort)],
            ['Official game files', downloading ? 'Still downloading' : 'Downloaded and verified'],
          ].map(([title, value]) => <div key={title}><dt>{title}</dt><dd>{value}</dd></div>)}</dl>
          <p className="first-run-hint">DST will prepare the database, connections and initial maps. You choose when to start your battlegroup after setup.</p>
        </>}
        {step === 6 && <>
          <p role="status" aria-live="polite">{running ? label || 'Finishing the current step…' : setupComplete(state) ? 'Your server is prepared. Continue to finish setup.' : 'Preparation needs your attention. Your saved progress is available below.'}</p>
          <ol className="first-run-progress">{stages.map(stage => <li key={stage.title} data-done={stage.done}><span aria-hidden="true">{stage.done ? '✓' : '○'}</span>{stage.title}<small>{stage.done ? 'Ready' : running ? 'Preparing' : 'Pending'}</small></li>)}</ol>
          <p className="first-run-hint">Preparation can take several minutes. Keep this page open. If you leave, return here to check progress and continue.</p>
        </>}
        {step === 7 && <>
          <p><strong>{state.profile?.name}</strong> is ready to manage. Your server storage, connections and initial maps have been prepared.</p>
          <div className="first-run-choice"><span className="first-run-choice-icon" aria-hidden="true">✓</span><div><h3>Setup complete</h3><p>Open the portal to review your settings and start your battlegroup when you’re ready.</p></div></div>
        </>}
      </div>
      <div className="first-run-controls">
        <button type="button" disabled={step === 0 || running || step === 7} onClick={() => goTo(step - 1)}>Back</button>
        {step === 7 ? <button type="button" className="first-run-primary" onClick={onFinish}>Open management portal</button>
          : <button type="submit" className="first-run-primary" disabled={running || (step >= 5 && downloading)}>{running ? 'Preparing…' : step === 5 ? 'Prepare server' : step === 6 ? 'Continue setup' : 'Next'}</button>}
      </div>
    </form>
  </SetupFrame>
}
