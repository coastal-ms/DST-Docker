// LandclaimTimerCard — collapse the game's staking-unit (land claim) extension
// schedule down to a single custom duration.
//
// The game ships a doubling schedule (60..30720s) for how long a land-claim
// staking-unit extension takes. Enabling this writes one admin-chosen "seconds"
// value into [/Script/DuneSandbox.BuildingSettings] as the two *DefaultTimes
// scalars, and strips every built-in schedule entry via array-remove (-) lines —
// into BOTH the server UserGame.ini and the local client Game.ini. Disabling
// removes DST's lines so the game defaults return.
import { useCallback, useEffect, useState } from 'react'
import { Icon } from '../../components/Icon'
import { CollapsibleCard } from '../../components/CollapsibleCard'
import { IniShareModal } from '../../components/IniShareModal'
import { ApiError } from '../../api/client'
import { ConfirmationModal } from '../../components/ConfirmationModal'
import { getLandclaimTimer, saveLandclaimTimer } from '../../api/gameconfig'
import type { LandclaimTimerState } from '../../api/types'
import { chooseBrowserClientFiles, isBrowserClientSelectionCancelled } from '../../api/browserClientFiles'

type Props = {
  vmRunning: boolean
}

export function LandclaimTimerCard({ vmRunning }: Props) {
  const docker = import.meta.env.VITE_DST_EDITION === 'docker'
  const [includeClient, setIncludeClient] = useState(false)
  const [state, setState] = useState<LandclaimTimerState | null>(null)
  const [enabled, setEnabled] = useState(false)
  const [seconds, setSeconds] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [warning, setWarning] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [showBlock, setShowBlock] = useState(false)
  const [reviewOpen, setReviewOpen] = useState(false)

  const seed = useCallback((s: LandclaimTimerState) => {
    // Prefer the server's live view; fall back to the local client file when the
    // VM is down so the form still reflects what's on disk.
    const src = s.server.available ? s.server : s.client
    setEnabled(src.enabled)
    setSeconds(src.enabled ? src.seconds : '')
  }, [])

  const load = useCallback(async () => {
    setLoading(true); setErr(null); setWarning(null)
    try {
      const s = await getLandclaimTimer()
      setState(s)
      seed(s)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [seed])

  useEffect(() => { void load() }, [load])

  const trimmed = seconds.trim()
  const num = Number(trimmed)
  const validSeconds = trimmed !== '' && Number.isFinite(num) && num > 0
  const server = state?.server

  // Include client mismatches so a skipped local write can be retried.
  const curEnabled = server?.available ? server.enabled : false
  const curSeconds = server?.available ? server.seconds : ''
  const client = state?.client
  const clientNeedsApply = (!docker || includeClient) && !!client?.dirExists && (enabled !== client.enabled ||
    (enabled && (trimmed !== client.seconds.trim() || !client.formattedOk)) ||
    (!enabled && client.hasOverrides === true))
  const dirty = enabled !== curEnabled || (enabled && (trimmed !== curSeconds.trim() || !server?.formattedOk)) ||
    (!enabled && server?.hasOverrides === true) || clientNeedsApply
  const canApply = vmRunning && (!docker || server?.available === true) && !saving && dirty && (!enabled || validSeconds)

  async function apply() {
    if (!canApply) return
    setSaving(true); setErr(null); setWarning(null); setOk(null)
    try {
      const r = docker ? await saveLandclaimTimer(enabled, enabled ? trimmed : '', includeClient) : await saveLandclaimTimer(enabled, enabled ? trimmed : '')
      setState({ server: r.server, client: r.client, clientBlock: r.clientBlock })
      seed({ server: r.server, client: r.client, clientBlock: r.clientBlock })
      const clientNote = r.result.client.applied
        ? ', client Game.ini updated'
        : ''
      if ((!docker || includeClient) && !r.result.client.ok) setWarning(`Client Game.ini was not updated: ${r.result.client.reason ?? 'client config folder unavailable'}`)
      setOk(enabled
        ? `Land-claim timer set to ${trimmed}s — server UserGame.ini updated${clientNote}.`
        : `Land-claim timer cleared — server game defaults restored${clientNote}.`)
      if (r.result.client.delivery === 'download') setWarning('Player Game.ini download prepared with exact original backup. No player file was installed. Close Dune, install the Updated file, then select it again to verify.')
      if (r.warning) setWarning(previous => [previous, r.warning].filter(Boolean).join(' '))
      // Client-side setting: surface the exact block so the admin can hand it to
      // connecting players (it only takes effect on their end if THEIR Game.ini
      // carries the same block).
      if (enabled && r.clientBlock) setShowBlock(true)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <CollapsibleCard
      id="gameconfig.landclaimTimer"
      icon="Timer"
      iconClassName="shrink-0 text-accent"
      title="Land Claim Timer"
      titleClassName="text-sm font-semibold text-text"
      subtitle={
        <span className="text-xs text-text-muted">
          Override how long a land-claim staking-unit extension takes (seconds).
        </span>
      }
      className="mb-4 border-border"
      headerClassName="px-4 pt-4 pb-2"
      bodyClassName="px-4 pb-4"
      headerRight={
        <button
          type="button"
          className="btn-secondary shrink-0"
          onClick={() => void load()}
          disabled={loading || saving || dirty}
          title="Reload current values"
        >
          <Icon name={loading ? 'Loader2' : 'RotateCcw'} size={14} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      }
    >

      <label className="mt-3 flex items-center gap-2 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={enabled}
          onChange={e => { setEnabled(e.target.checked); setOk(null); setErr(null); setWarning(null) }}
          disabled={!vmRunning || saving}
          className="h-4 w-4 accent-accent"
        />
        <span className="text-sm text-text">Use a custom land-claim timer</span>
      </label>

      {enabled && (
        <div className="mt-3">
          <label htmlFor="landclaim-timer-seconds" className="block text-xs uppercase tracking-wider text-text-dim mb-1">Timer (seconds)</label>
          <input
            id="landclaim-timer-seconds"
            type="number"
            min={0}
            step="any"
            value={seconds}
            onChange={e => { setSeconds(e.target.value); setOk(null); setErr(null); setWarning(null) }}
            disabled={!vmRunning || saving}
            className="w-40 px-3 py-2 rounded-lg bg-surface-2 border border-border text-text focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent/50"
          />
          {trimmed !== '' && !validSeconds && (
            <div className="mt-1 text-xs text-danger">Enter a positive number of seconds.</div>
          )}
        </div>
      )}

      <div className="card p-3 mt-3 border-border bg-surface-2/40 text-xs text-text-muted flex items-start gap-2">
        <Icon name="Info" size={14} className="mt-0.5 shrink-0 text-accent-bright" />
        <div className="leading-relaxed">
          {docker ? <>Saves the server <span className="font-mono">UserGame.ini</span>. You can separately select this PC&apos;s player <span className="font-mono">Game.ini</span> below.</> : <>Applies to both the server <span className="font-mono">UserGame.ini</span> and the DST host PC&apos;s client <span className="font-mono"> Game.ini</span> (when the client config folder is set).</>} Connecting players
          need the same client value for the change to take effect on their end — share your DST-managed
          <span className="font-mono"> Game.ini</span> block. Disabling restores the game&apos;s default schedule.
        </div>
      </div>

      {docker && <div className="mt-3 rounded-lg border border-border p-3 text-sm">
        <button type="button" className="btn-secondary mb-3" disabled={saving || loading} onClick={() => {
          setLoading(true); setErr(null)
          void chooseBrowserClientFiles().then(async () => { setState(await getLandclaimTimer()); setIncludeClient(true) })
            .catch(e => { if (!isBrowserClientSelectionCancelled(e)) setErr(e instanceof Error ? e.message : String(e)) }).finally(() => setLoading(false))
        }}>Choose player config</button>
        <label className="flex items-start gap-2"><input type="checkbox" checked={includeClient} disabled={saving || !client?.dirExists} onChange={e => setIncludeClient(e.target.checked)} />
          <span>{client?.browserDelivery === 'download' ? 'Also prepare this PC’s player Game.ini download' : 'Also save this PC’s selected player Game.ini'}<span className="block text-xs text-text-muted">Close Dune before changing player files. Downloads include originals and must be installed manually.</span></span>
        </label>
        {client?.reason && <p className="mt-2 text-xs text-warning">{client.reason}</p>}
      </div>}

      {state && (
        <div className="mt-3 text-xs text-text-muted space-y-1">
          <div>
            Server:{' '}
            {!server?.available
              ? <span className="text-text-dim italic">unavailable{server?.reason ? ` (${server.reason})` : ''}</span>
              : server.enabled
                ? <span className="text-success">custom {server.seconds}s{server.formattedOk ? '' : ' (needs re-apply)'}</span>
                : <span className="text-text-dim">game default</span>}
          </div>
          <div>
            Client Game.ini:{' '}
            {!state.client.exists
              ? <span className="text-text-dim italic">{docker ? 'not selected' : 'not found'}{state.client.dir ? ` at ${state.client.dir}` : ''}</span>
              : state.client.enabled
                ? <span className="text-success">custom {state.client.seconds}s</span>
                : <span className="text-text-dim">game default</span>}
          </div>
        </div>
      )}

      <div className="mt-3 flex items-center gap-2">
        <button type="button" className="btn-primary" onClick={() => setReviewOpen(true)} disabled={!canApply}>
          <Icon name={saving ? 'Loader2' : 'Check'} size={14} className={saving ? 'animate-spin' : ''} />
          {saving ? 'Applying…' : enabled ? 'Review timer changes' : 'Review restore defaults'}
        </button>
        {state?.clientBlock && (
          <button type="button" className="btn-secondary" onClick={() => setShowBlock(true)}>
            <Icon name="Share2" size={14} /> Players&apos; Game.ini snippet
          </button>
        )}
      </div>

      {!vmRunning && (
        <div className="mt-2 text-xs text-text-dim">Start the VM to change the server value.</div>
      )}
      {err && (
        <div className="mt-3 text-sm text-danger flex items-center gap-2">
          <Icon name="AlertCircle" size={14} /> {err}
        </div>
      )}
      {warning && (
        <div role="status" className="mt-3 text-sm text-warning flex items-start gap-2">
          <Icon name="AlertTriangle" size={14} className="mt-0.5 shrink-0" /> <span>{warning}</span>
        </div>
      )}
      {ok && (
        <div className="mt-3 text-sm text-success flex items-start gap-2">
          <Icon name="ShieldCheck" size={14} className="mt-0.5 shrink-0" /> <span>{ok}</span>
        </div>
      )}

      {showBlock && state?.clientBlock && (
        <IniShareModal
          block={state.clientBlock}
          subtitle={<>The land-claim timer is client-side too. For it to work on a player&apos;s end, they must add this exact block to their own <span className="font-mono">Game.ini</span>.</>}
          onClose={() => setShowBlock(false)}
        />
      )}
      {reviewOpen && <ConfirmationModal title="Review land-claim timer" description={`This ${enabled ? `sets a ${trimmed}-second timer` : 'restores the default schedule'} in the server UserGame.ini${docker ? includeClient ? client?.browserDelivery === 'download' ? ' and prepares a reviewed player Game.ini download with original backup; the download is not installed automatically' : ' and this PC’s explicitly selected player Game.ini' : ' only; no player file will be changed' : ' and the DST host PC’s player Game.ini when its folder is available'}. Other players need their own matching value. This action is separate from the server-settings field review; deploy the server file with Review & Apply afterward.`} confirmLabel={docker ? includeClient ? client?.browserDelivery === 'download' ? 'Save server & Download player file' : 'Save server & selected player file' : 'Save server file' : 'Save server & host PC'} onCancel={() => setReviewOpen(false)} onConfirm={() => { setReviewOpen(false); void apply() }} />}
    </CollapsibleCard>
  )
}
