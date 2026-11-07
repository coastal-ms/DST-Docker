import { useEffect, useState } from 'react'
import { getGameConfigClient, saveLabLocal } from '../../api/gameconfig'
import type { GameConfigClientInfo, GameConfigRawUpdate } from '../../api/types'
import { isLocalViewer } from '../../util/viewer'
import { browserClientFolderSelected, chooseBrowserClientFolder } from '../../api/browserClientFiles'

export function LabSaveReview({ updates, serverPaths, serverAvailable = true, serverOnly = false, onServerSave, onDone, onCancel }: {
  serverOnly?: boolean
  updates: GameConfigRawUpdate[]
  serverPaths?: { game: string; engine: string }
  serverAvailable?: boolean
  onServerSave: () => Promise<unknown>
  onDone: (message: string) => void
  onCancel: () => void
}) {
  const docker = import.meta.env.VITE_DST_EDITION === 'docker'
  const localViewer = isLocalViewer() || docker
  const [client, setClient] = useState<GameConfigClientInfo | null>(null)
  const [localError, setLocalError] = useState('')
  const [local, setLocal] = useState(localViewer && !serverOnly && (!docker || browserClientFolderSelected()))
  const [server, setServer] = useState(serverAvailable)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [serverSaved, setServerSaved] = useState(false)
  const [localSaved, setLocalSaved] = useState(false)
  const [localDownloaded, setLocalDownloaded] = useState(false)
  const [localValidated, setLocalValidated] = useState(false)
  useEffect(() => {
    if (!localViewer) return
    let active = true
    void getGameConfigClient().then(info => {
      if (active) setClient(info)
    }).catch(e => { if (active) setLocalError(String(e)) })
    return () => { active = false }
  }, [localViewer])

  async function save() {
    setBusy(true); setError('')
    let staged = serverSaved
    let written = localSaved
    let downloaded = localDownloaded
    let validated = localValidated
    try {
      // Do the local write first: a running game must not leave a surprise
      // server-only save. Each completed destination remains visible on retry.
      if (local && !written) {
        const result = await saveLabLocal(updates)
        downloaded = result.delivery === 'download'; setLocalDownloaded(downloaded)
        validated = result.delivery === 'validated'; setLocalValidated(validated)
        written = true; setLocalSaved(true)
      }
      if (server && !staged) {
        await onServerSave()
        staged = true; setServerSaved(true)
      }
      onDone([
        written ? downloaded ? 'Client settings package downloaded with original backups. No local file was installed. Close Dune, install the Updated files, then select them again to verify.' : validated ? 'Selected client files already match the reviewed changes. No file was changed.' : 'Local Solo/player INIs saved and verified; existing files backed up. Restart the game to test.' : '',
        staged ? 'Server INIs saved. Use Apply server settings to deploy them to the self-hosted server.' : '',
      ].filter(Boolean).join(' '))
    } catch (e) {
      setError(`${written ? downloaded ? 'Client download prepared. ' : validated ? 'Client files checked. ' : 'Local files saved. ' : ''}${staged ? 'Server files saved. ' : ''}${e instanceof Error ? e.message : String(e)} Pending destinations have not been saved.`)
    } finally { setBusy(false) }
  }

  return <div className="fixed inset-0 z-[100] bg-black/60 flex items-center justify-center p-4">
    <section role="dialog" aria-modal="true" aria-labelledby="lab-save-title" className="card p-5 w-full max-w-2xl max-h-[85vh] overflow-y-auto space-y-4">
      <h2 id="lab-save-title" className="text-lg font-semibold">Review Lab save destinations</h2>
      <p className="text-sm text-text-muted">Choose where to save. Local files affect Solo and this PC’s player. Server files take effect after Apply server settings.</p>
      <label className="flex gap-2"><input type="checkbox" checked={local} disabled={serverOnly || !localViewer || busy || localSaved || (docker && !client?.dirExists)} onChange={e => setLocal(e.target.checked)} />
        {client?.browserDelivery === 'download' ? 'Prepare this PC’s Solo/player file download' : 'Save to this PC’s local Solo/player files'} {localSaved && (localDownloaded ? '(downloaded)' : localValidated ? '(checked)' : '(saved)')}</label>
      {docker && localViewer && !serverOnly && !client?.dirExists && <button type="button" className="btn-secondary" disabled={busy} onClick={() => {
        setBusy(true); setError('')
        void chooseBrowserClientFolder().then(info => { setClient(info); setLocal(true) }).catch(e => setError(e instanceof Error ? e.message : String(e))).finally(() => setBusy(false))
      }}>Choose client config</button>}
      {localViewer ? <div className="text-xs text-text-muted break-all">
        {client ? [...new Set(updates.map(u => u.file))].map(file => <div key={file}>{file === 'engine' ? client.engine.path : (client.game ?? client).path}</div>) : localError || 'Reading local file locations…'}
        <p>Approval applies only to the listed edits. Existing files are backed up; unrelated values stay intact. Close Dune: Awakening before saving local files.</p>
        {client?.browserDelivery === 'download' && <p>The download contains Updated files and exact Original backups. You must install the Updated files manually, then select them again to verify. Your originals are not changed by downloading.</p>}
      </div> : <p className="text-xs text-text-muted">Local file changes require opening DST on the host PC. You can still save the server copy here.</p>}
      <label className="flex gap-2"><input type="checkbox" checked={server} disabled={busy || serverSaved || !serverAvailable} onChange={e => setServer(e.target.checked)} />Save to self-hosted server INIs {serverSaved && '(saved)'}</label>
      {!serverAvailable && <p className="text-xs text-text-muted">Server unavailable. Local saves remain available; reconnect to save the server copy.</p>}
      <p className="text-xs text-text-muted">Game → server UserGame.ini · Engine → server UserEngine.ini. Save stages these changes without restarting the battlegroup.</p>
      {serverPaths && <div className="text-xs text-text-muted break-all">{[...new Set(updates.map(u => u.file))].map(file => <div key={file}>{serverPaths[file]}</div>)}</div>}
      <ul className="space-y-2 text-xs font-mono max-h-60 overflow-y-auto">
        {updates.map(u => <li key={`${u.file}||${u.section}||${u.key}`} className="border border-border p-2 rounded break-all">
          <div>{u.file === 'game' ? 'Game.ini / UserGame.ini' : 'Engine.ini / UserEngine.ini'} [{u.section}]</div>
          <div>{u.key} → {u.arrayLines ? u.arrayLines.join('\n') || 'Remove array entries' : u.value?.trim() ? u.value : 'Remove override; use inherited default'}</div>
          {client && <div className="text-text-muted">Local now: {(u.file === 'engine' ? client.engine : client.game ?? client).effective[`${u.section}||${u.key}`] ?? 'No override'}</div>}
        </li>)}
      </ul>
      {error && <p role="alert" className="text-danger text-sm">{error}</p>}
      <div className="flex justify-end gap-2">
        <button type="button" className="btn-secondary" disabled={busy} onClick={onCancel}>Cancel</button>
        <button type="button" className="btn-primary" disabled={busy || (!local && !server) || (local && !client)} onClick={() => void save()}>{busy ? 'Saving…' : local ? client?.browserDelivery === 'download' ? 'Approve changes & Download' : 'Approve local changes & Save' : 'Save server files'}</button>
      </div>
    </section>
  </div>
}
