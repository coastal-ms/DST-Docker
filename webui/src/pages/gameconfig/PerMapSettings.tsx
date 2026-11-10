import { useEffect, useMemo, useRef, useState } from 'react'
import { api, withOnlinePlayerGuard } from '../../api/client'
import { ConfirmationModal } from '../../components/ConfirmationModal'
import { NumericSettingControl, RETAIL_SETTING_GUIDANCE } from './OfficialRetailServerSettingsCard'
import { Link } from '../../router'
import { Icon } from '../../components/Icon'

type File = 'server' | 'game' | 'engine'
type Field = { id: string; key: string; label: string; group: string; type: string; value: string; editable: boolean; inverted?: boolean; default?: string; help?: string; min?: number; max?: number; clientApply?: boolean; options?: (string | { value: string; label: string })[] }
type Target = { id: string; map: string; label: string }
type Snapshot = { targets: Target[]; target: string; file: File; revision: string; raw: string; overridden: boolean; pendingRestart: boolean; adapterReady: boolean; running?: boolean; fields: Field[] }
const fileNames: Record<File, string> = { server: 'Custom Settings', game: 'Game', engine: 'Engine' }
const globalTarget: Target = { id: 'global', map: 'global', label: 'Global defaults · all maps' }
const draftKey = (target: string, file: File) => `dst.docker.map-draft.${target}.${file}`
function savedChoice(key: string) {
  try { return sessionStorage.getItem(`dst.docker.map-settings.${key}`) ?? '' } catch { return '' }
}
function readDraft(target: string, file: File): { snapshot: Snapshot; values: Record<string, string> } | null {
  try {
    const draft = JSON.parse(sessionStorage.getItem(draftKey(target, file)) ?? 'null')
    return draft?.snapshot?.target === target && draft.snapshot.file === file && draft.values && Array.isArray(draft.snapshot.fields) ? draft : null
  } catch { return null }
}
const valuesFrom = (snapshot: Snapshot) => Object.fromEntries(snapshot.fields.map(field => [field.id, field.value]))
const messageOf = (error: unknown) => error instanceof Error ? error.message : String(error)

function validation(field: Field, value: string) {
  if (!field.editable || value === '') return ''
  if (field.type === 'int' || field.type === 'float') {
    const number = Number(value)
    if (!Number.isFinite(number) || (field.type === 'int' && !/^-?\d+$/.test(value))) return 'Enter a valid ' + (field.type === 'int' ? 'whole number.' : 'number.')
    if (field.min !== undefined && number < field.min) return `Minimum: ${field.min}`
    if (field.max !== undefined && number > field.max) return `Maximum: ${field.max}`
  }
  return ''
}

export function PerMapSettings({ onDirtyChange, onTargetChange, initialTarget = '', scopeLocked = false }: { onDirtyChange?: (dirty: boolean) => void; onTargetChange?: (target: string) => void; initialTarget?: string; scopeLocked?: boolean }) {
  const [targets, setTargets] = useState<Target[]>([globalTarget])
  const [target, setTarget] = useState(() => initialTarget || savedChoice('target') || 'global')
  const [file, setFile] = useState<File>(() => { const saved = savedChoice('file'); return saved === 'game' || saved === 'engine' ? saved : 'server' })
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [category, setCategory] = useState('')
  const [query, setQuery] = useState(() => savedChoice('query'))
  const [view, setView] = useState<'grid' | 'list'>(() => savedChoice('view') === 'list' ? 'list' : 'grid')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [review, setReview] = useState<'inherit' | 'restart' | null>(null)
  const [switchTo, setSwitchTo] = useState<{ target: string; file: File } | null>(null)
  const [restartTick, setRestartTick] = useState(0)
  const [restartInFlight, setRestartInFlight] = useState(false)
  const [mapProgress, setMapProgress] = useState<{ phase: string; detail: string } | null>(null)
  const editorState = useRef({ dirty: false, pending: false })
  const sequence = useRef(0)
  const snapshotMatches = snapshot?.target === target && snapshot?.file === file
  const fields = snapshotMatches ? snapshot.fields : []
  const changes = useMemo(() => Object.fromEntries(fields.filter(field => field.editable && (values[field.id] ?? '') !== field.value).map(field => [field.id, values[field.id] ?? ''])), [fields, values])
  const dirty = Object.keys(changes).length > 0
  const invalid = fields.some(field => validation(field, values[field.id] ?? ''))
  const global = target === 'global'
  editorState.current = { dirty, pending: !!snapshot?.pendingRestart }
  const label = targets.find(item => item.id === target)?.label ?? 'selected map'
  useEffect(() => {
    try { for (const [key, value] of Object.entries({ target, file, query, view })) sessionStorage.setItem(`dst.docker.map-settings.${key}`, value) } catch { /* Storage may be disabled. */ }
  }, [target, file, query, view])

  useEffect(() => { onDirtyChange?.(dirty); return () => onDirtyChange?.(false) }, [dirty, onDirtyChange])
  useEffect(() => {
    if (!dirty) return
    const prevent = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', prevent)
    return () => window.removeEventListener('beforeunload', prevent)
  }, [dirty])

  const load = async (selected: string, kind: File) => {
    const request = ++sequence.current
    setBusy(true); setError(''); setSnapshot(null)
    try {
      const catalog = await api<{ targets: Target[] }>(`/api/docker/map-settings?file=${kind}`)
      if (request !== sequence.current) return
      const available = [globalTarget, ...catalog.targets.filter(item => item.id !== 'global' && /^(?:Survival|DeepDesert)_[1-9][0-9]*$/.test(item.map))]
      setTargets(available)
      if (!available.some(item => item.id === selected)) { setTarget('global'); onTargetChange?.('global'); return }
      const result = await api<Snapshot>(`/api/docker/map-settings?target=${encodeURIComponent(selected)}&file=${kind}`)
      if (request !== sequence.current) return
      if (selected) {
        const draft = readDraft(selected, kind)
        setSnapshot(draft?.snapshot ?? result); setValues(draft?.values ?? valuesFrom(result))
        if (draft && draft.snapshot.revision !== result.revision) setError('The saved file changed while you were away. Your draft is preserved; discard it and Refresh to load the current file.')
      }
      else if (result.targets.length) setTarget(result.targets[0].id)
    } catch (e) { if (request === sequence.current) setError(messageOf(e)) }
    finally { if (request === sequence.current) setBusy(false) }
  }
  useEffect(() => { void load(target, file); return () => { sequence.current++ } }, [target, file])
  useEffect(() => {
    if (!snapshotMatches) return
    try {
      if (dirty) sessionStorage.setItem(draftKey(target, file), JSON.stringify({ snapshot, values }))
      else sessionStorage.removeItem(draftKey(target, file))
    } catch { /* Editing remains available when browser storage is disabled. */ }
  }, [target, file, snapshot, snapshotMatches, values, dirty])
  const select = (nextTarget: string, nextFile: File) => {
    if (scopeLocked && nextTarget !== target) return
    if (nextTarget === target && nextFile === file) return
    if (dirty) { setSwitchTo({ target: nextTarget, file: nextFile }); return }
    setTarget(nextTarget); setFile(nextFile); setCategory(''); setMessage('')
    if (nextTarget !== target) onTargetChange?.(nextTarget)
  }
  const save = async (inherit: boolean) => {
    if (!snapshotMatches || busy) return
    setReview(null); setBusy(true); setError(''); setMessage('')
    try {
      const result = await api<Snapshot>('/api/docker/map-settings', { method: 'PUT', body: JSON.stringify({ target, file, revision: snapshot.revision, updates: changes, inherit }) })
      setSnapshot(result); setValues(valuesFrom(result))
      setMessage(global ? `${fileNames[file]} saved as Global defaults. Maps without their own copy use these values at their next start.` : `${fileNames[file]} saved for ${label}. ${result.pendingRestart ? 'Pending restart: this map will read the saved file at its next start.' : 'No restart is pending.'}`)
      try { sessionStorage.removeItem(draftKey(target, file)) } catch { /* Storage may be disabled. */ }
    } catch (e) { setError(messageOf(e)) }
    finally { setBusy(false) }
  }
  const restart = async () => {
    setReview(null); setBusy(true); setError('')
    setRestartInFlight(true); setMapProgress({ phase: 'Restarting', detail: `Requesting a restart of ${label}…` })
    try {
      await withOnlinePlayerGuard(force => api(`/api/docker/map-settings/restart${force ? '?force=true' : ''}`, { method: 'POST', body: JSON.stringify({ target }) }))
      setMessage(''); setRestartTick(value => value + 1)
    } catch (e) { setError(messageOf(e)); setRestartInFlight(false); setMapProgress({ phase: 'Restart failed', detail: messageOf(e) }) }
    finally { setBusy(false) }
  }
  useEffect(() => { setMapProgress(null); setRestartInFlight(false) }, [target, file])
  useEffect(() => {
    if (!target || target === 'global') return
    let stopped = false, checking = false, refreshed = false
    const check = async () => {
      if (checking) return
      checking = true
      try {
        const status = await api<{ metadata?: { operation?: { action: string; phase: string; partition?: number; error?: string }; services: { component: string; state: string; gameReady?: boolean }[] } }>('/api/docker/maps')
        if (stopped || !status.metadata) return
        const service = status.metadata.services.find(row => row.component === `game-${target}`)
        const operation = status.metadata.operation
        const ownRestart = operation?.action === 'maps.restart' && String(operation.partition) === target
        const failed = ownRestart && ['failed', 'interrupted'].includes(operation.phase)
        const restarting = ownRestart && operation.phase === 'running'
        const loading = !failed && !restarting && service?.state === 'running' && service.gameReady !== true
        setRestartInFlight(!!restarting || loading)
        setMapProgress(failed ? { phase: 'Restart failed', detail: operation.error || 'The restart did not finish. Review the error before retrying.' }
          : restarting ? { phase: 'Restarting', detail: `${label} is stopping and starting. Please wait.` }
          : loading ? { phase: 'Loading', detail: `${label} is running and waiting for its game-ready heartbeat.` }
          : service?.gameReady ? { phase: 'Ready', detail: `${label} has reported ready.` }
          : { phase: 'Stopped', detail: `${label} is not running.` })
        if (ownRestart && operation.phase === 'completed' && service?.gameReady && editorState.current.pending && !editorState.current.dirty && !refreshed) {
          refreshed = true; void load(target, file)
        }
      } catch (e) {
        if (!stopped) setMapProgress({ phase: 'Status unavailable', detail: `The restart status could not be checked: ${messageOf(e)}. Checking again automatically.` })
      } finally { checking = false }
    }
    void check()
    const timer = window.setInterval(() => { void check() }, 4_000)
    return () => { stopped = true; window.clearInterval(timer) }
  }, [target, file, restartTick])
  const categories = [...new Set(fields.map(field => field.group))]
  const visible = fields.filter(field => (!category || field.group === category) && `${field.label} ${field.key} ${field.help ?? ''}`.toLowerCase().includes(query.toLowerCase()))
  return <section className="card space-y-4 p-4 sm:p-5" aria-label="Per-map settings">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><h2 className="text-lg font-semibold">Map settings</h2><p className="mt-1 text-sm text-text-muted">{label} · {fileNames[file]}</p></div><span className="rounded border border-border px-3 py-1 text-sm">{dirty ? 'Unsaved changes' : snapshot?.pendingRestart ? snapshot.running === false ? 'Saved · next start' : 'Saved · pending restart' : global ? 'Global defaults' : 'Saved settings'}</span></div>
    <div className="flex flex-wrap gap-2" aria-label="Map settings files">{(Object.keys(fileNames) as File[]).map(kind => <button key={kind} type="button" disabled={busy} aria-pressed={kind === file} className={kind === file ? 'btn-primary' : 'btn-secondary'} onClick={() => select(target, kind)}>{fileNames[kind]}</button>)}</div>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-[2fr_1fr_2fr_auto]">
      <label className="space-y-1 text-sm">Settings scope<select className="map-management-input w-full" value={target} disabled={busy || scopeLocked} onChange={event => select(event.target.value, file)}>{!targets.length && <option value="">Select a map</option>}{targets.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
      <label className="space-y-1 text-sm">Setting category<select className="map-management-input w-full" value={category} onChange={event => setCategory(event.target.value)}><option value="">All ({fields.length})</option>{categories.map(group => <option key={group}>{group}</option>)}</select></label>
      <label className="space-y-1 text-sm">Find a setting<input className="map-management-input w-full" type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Name, key or description" /></label>
      <div className="flex items-end gap-1" aria-label="Settings view">{(['grid', 'list'] as const).map(mode => <button type="button" key={mode} aria-pressed={view === mode} className={view === mode ? 'btn-primary' : 'btn-secondary'} onClick={() => setView(mode)}>{mode === 'grid' ? 'Grid' : 'List'}</button>)}</div>
    </div>
    {busy && <p role="status">Loading or saving map settings…</p>}
    {error && <p role="alert" className="text-danger">{error}</p>}
    {message && <p role="status" className="rounded-lg border border-success/40 p-3 text-success">{message}</p>}
    {!global && mapProgress && <div role="status" aria-live="polite" className="flex items-center gap-3 rounded-lg border border-border p-3 text-sm">
      {restartInFlight && <Icon name="Loader2" size={18} className="animate-spin shrink-0" />}
      <p><strong>{mapProgress.phase}</strong> · {mapProgress.detail}</p>
    </div>}
    {snapshotMatches && <>
      <div className="rounded-lg border border-border p-3 text-sm"><strong>Editing: {label} · {fileNames[file]}</strong><p className="mt-1 text-text-muted">{global ? 'Defaults for all maps. A map with its own saved file keeps that copy. Changes apply at the next map start.' : snapshot.overridden ? 'This map uses its own saved file. Future global edits will not replace it.' : 'Currently using the global file. Saving creates an independent copy for this map.'}{!global && ' Changes take effect when this map starts again.'}</p></div>
      {!snapshot.adapterReady && <p className="text-warning">This map needs the updated DST adapter before per-map saves are available. Existing settings are preserved.</p>}
      {!global && snapshot.pendingRestart && <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warning/40 p-3"><p><strong>{snapshot.running === false ? 'Saved for next start' : 'Pending restart'}</strong> · {snapshot.running === false ? `${label} is stopped. Its saved settings will load when it next starts.` : `Saved settings for ${label} have not been loaded by a new map process.`}</p>{snapshot.running !== false && <button type="button" className="btn-secondary" disabled={busy || dirty || restartInFlight} onClick={() => setReview('restart')}>{restartInFlight ? 'Restart in progress…' : 'Restart this map'}</button>}<button type="button" className="btn-secondary" disabled={busy || dirty} onClick={() => void load(target, file)}>Check applied status</button></div>}
      {global && file === 'server' && <p className="text-sm text-text-muted">Stop the battlegroup before saving global Custom Settings. Saving does not start maps.</p>}
      {file === 'server' && <p className="text-sm text-text-muted">Custom Settings and UserGame PvP controls can overlap. Review both files when changing PvP.</p>}
      {file !== 'server' && <p className="text-sm text-text-muted">Structured settings are shown here. Complex arrays and startup console variables remain in the specialized global controls. Settings marked “Player files too” also require matching client configuration.</p>}
      <div className={view === 'grid' ? 'grid gap-3 md:grid-cols-2 xl:grid-cols-3' : 'space-y-3'}>{visible.map(field => {
        const guidance = file === 'server' ? RETAIL_SETTING_GUIDANCE[field.key] : undefined
        const defaultValue = field.default ?? guidance?.defaultValue
        const value = values[field.id] ?? ''
        const problem = validation(field, value)
        const options = field.type === 'bool' ? [{ value: 'True', label: field.inverted ? 'Disabled' : 'Enabled' }, { value: 'False', label: field.inverted ? 'Enabled' : 'Disabled' }] : field.options ?? []
        return <div key={field.id} className="min-w-0 space-y-2 rounded-lg border border-border bg-surface p-4">
          <label htmlFor={`map-setting-${field.id}`} className="block font-semibold">{field.label}</label><p className="break-all font-mono text-xs text-text-muted">{field.key}</p>
          {(field.help || guidance?.effect) && <p className="text-sm text-text-muted">{field.help ?? guidance?.effect}</p>}
          <div>{options.length ? <select id={`map-setting-${field.id}`} className="map-management-input w-full" disabled={busy || !field.editable} value={value} onChange={event => setValues(previous => ({ ...previous, [field.id]: event.target.value }))}><option value="">Game default (unset)</option>{options.map(option => { const item = typeof option === 'string' ? { value: option, label: option } : option; return <option key={item.value} value={item.value}>{item.label}</option> })}</select> : ['int', 'float'].includes(field.type) ? <NumericSettingControl inputId={`map-setting-${field.id}`} setting={{ key: field.key, label: field.label, type: field.type as 'int' | 'float', value: field.value || defaultValue || '0', valid: true, min: field.min, max: field.max }} disabled={busy || !field.editable} value={value} wheelOnHover showUnsetSlider onChange={next => setValues(previous => ({ ...previous, [field.id]: next }))} onCommit={() => {}} /> : <input id={`map-setting-${field.id}`} className="map-management-input w-full" disabled={busy || !field.editable} value={value} placeholder={defaultValue ? `Game default: ${defaultValue}` : 'Not configured'} onChange={event => setValues(previous => ({ ...previous, [field.id]: event.target.value }))} />}</div>
          {(field.min !== undefined || field.max !== undefined) && <p className="text-xs text-text-muted">Allowed: {field.min ?? 'no minimum'}–{field.max ?? 'no maximum'}</p>}
          {field.clientApply && <p className="text-xs text-warning">Player files too</p>}
          {problem && <p role="alert" className="text-sm text-danger">{problem}</p>}
          {defaultValue !== undefined && field.editable && <button type="button" className="text-xs text-accent" disabled={busy} onClick={() => setValues(previous => ({ ...previous, [field.id]: defaultValue }))}>Use default ({defaultValue})</button>}
        </div>
      })}</div>
      {!visible.length && <p>No settings match this filter.</p>}
      <div className="sm:sticky bottom-2 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-base p-3 shadow-lg">
        <button type="button" className="btn-primary" disabled={!dirty || !!invalid || busy || !snapshot.adapterReady} onClick={() => void save(false)}>{global ? 'Save global defaults' : 'Save map settings'}{dirty ? ` (${Object.keys(changes).length})` : ''}</button>
        <button type="button" className="btn-secondary" disabled={!dirty || busy} onClick={() => { setValues(valuesFrom(snapshot)); setError('') }}>Discard changes</button>
        <button type="button" className="btn-secondary" disabled={busy} onClick={() => setValues(previous => {
          const next = { ...previous }
          for (const field of fields) {
            const value = field.default ?? (file === 'server' ? RETAIL_SETTING_GUIDANCE[field.key]?.defaultValue : undefined)
            if (field.editable && value !== undefined) next[field.id] = value
          }
          return next
        })}>Restore defaults</button>
        <button type="button" className="btn-secondary" disabled={busy || dirty} onClick={() => void load(target, file)}>Refresh</button>
        {!global && <button type="button" className="btn-secondary" disabled={!snapshot.overridden || dirty || busy || !snapshot.adapterReady} onClick={() => setReview('inherit')}>Use global settings</button>}
        <span className="text-xs text-text-muted">Save now; apply at the next map start.</span>
      </div>
      <details className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-sm">View saved INI for {label}</summary><p className="my-2 text-xs text-text-muted">The saved file is shown here. Unsaved changes above are not included.</p><textarea className="map-management-input h-56 w-full font-mono text-xs" aria-label="Saved map INI" readOnly value={snapshot.raw} /></details>
    </>}
    <div className="flex flex-wrap gap-3 text-sm"><button type="button" className="text-accent" disabled={busy || scopeLocked} onClick={() => select('global', file)}>Global defaults</button><Link to="/server-settings?section=tools" className="text-accent">Specialized editors</Link><Link to="/map?view=lifecycle" className="text-accent">Back to Maps &amp; memory</Link></div>
    {switchTo && <ConfirmationModal title="Discard these map changes?" description={`Your unsaved ${fileNames[file]} changes for ${label} will be discarded before switching.`} confirmLabel="Discard & switch" onCancel={() => setSwitchTo(null)} onConfirm={() => { try { sessionStorage.removeItem(draftKey(target, file)) } catch { /* Storage may be disabled. */ } setValues({}); setTarget(switchTo.target); setFile(switchTo.file); setCategory(''); setMessage(''); if (switchTo.target !== target) onTargetChange?.(switchTo.target); setSwitchTo(null) }} />}
    {review && <ConfirmationModal title={review === 'restart' ? `Restart ${label}?` : 'Use the global file for this map?'} description={review === 'restart' ? 'Players on this map will disconnect. DST will request a restart of this partition; check Server Overview for readiness.' : 'This removes this map’s override for the selected settings file. A backup is kept. The global file will apply at this map’s next start.'} confirmLabel={review === 'restart' ? 'Restart this map' : 'Use global settings'} onCancel={() => setReview(null)} onConfirm={() => review === 'restart' ? void restart() : void save(true)} />}
  </section>
}
