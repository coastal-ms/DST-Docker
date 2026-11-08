import { useEffect, useState } from 'react'
import { getLandclaimTimer } from '../../api/gameconfig'
import { Icon } from '../../components/Icon'

type Entry = { file: 'game' | 'engine'; path: string; block: string }
const folder = '%LOCALAPPDATA%\\DuneSandbox\\Saved\\Config\\Windows'

export function buildDockerClientInstructions(entries: Entry[], timerBlock = '') {
  const files = (['game', 'engine'] as const).flatMap(file => {
    const blocks = entries.filter(entry => entry.file === file)
    const text = [...blocks.map(entry => entry.block), ...(file === 'game' && timerBlock ? [timerBlock] : [])].join('\n\n')
    return text ? [`${file === 'game' ? 'Game.ini' : 'Engine.ini'} - matching saved server values`, `${folder}\\${file === 'game' ? 'Game.ini' : 'Engine.ini'}`, text, ''] : []
  })
  return [
    'Dune player compatibility — manual instructions',
    'These changes are for each player’s Windows game files. Docker manages the server files separately.',
    '',
    '1. Close Dune: Awakening.',
    `2. Press Win+R, enter ${folder}, and open that folder.`,
    '3. Back up the existing Game.ini and Engine.ini before editing.',
    '4. Open the indicated file in a text editor. Find each section and update only the listed keys. Keep unrelated settings. Create a missing file only if a block below requires it.',
    '5. Remove earlier DST compatibility overrides that are no longer listed, restoring their game defaults. Remove only entries you previously added for DST; keep unrelated settings.',
    '6. Save the files, then start the game. Each player makes these changes on their own PC.',
    'Engine.ini changes affect every server that player joins. To undo these edits, close the game and restore the backup.',
    '',
    ...files,
    ...(!entries.length && !timerBlock ? ['No additional advanced compatibility overrides are listed for the current saved server settings.'] : []),
  ].join('\n')
}

export function DockerClientInstructions({ entries, ready }: { entries: Entry[]; ready: boolean }) {
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const refresh = () => setRevision(value => value + 1)
    window.addEventListener('dst:player-instructions', refresh)
    return () => window.removeEventListener('dst:player-instructions', refresh)
  }, [])
  const [loadingTimer, setLoadingTimer] = useState(true)
  const [timerBlock, setTimerBlock] = useState('')
  const [timerError, setTimerError] = useState('')
  const [message, setMessage] = useState('')
  useEffect(() => {
    let closed = false
    setLoadingTimer(true)
    if (ready) void getLandclaimTimer().then(state => {
      if (!state.server.available) throw new Error('Server timer unavailable')
      if (!closed) { setTimerBlock(state.server.available && state.server.enabled ? state.clientBlock ?? '' : ''); setTimerError('') }
    }).catch(() => { if (!closed) setTimerError('Land-claim timer instructions could not be read. Check the timer under Specialized controls before sharing these instructions.') }).finally(() => { if (!closed) setLoadingTimer(false) })
    return () => { closed = true }
  }, [ready, entries, revision])
  const instructions = buildDockerClientInstructions(entries, timerBlock)
  return <section className="card p-4 mb-4" aria-labelledby="docker-player-instructions">
    <h2 id="docker-player-instructions" className="font-semibold text-text mb-2">Player compatibility instructions</h2>
    <p className="text-sm text-text-muted mb-3">Each player updates their own game files. These instructions reflect saved server settings. Close the game and back up the files before editing.</p>
    <p className="text-xs text-text-muted mb-3">Windows player folder: <code className="break-all">{folder}</code>. The Docker host does not need access to this folder.</p>
    {!ready ? <p role="status" className="text-sm text-text-muted">Load the saved server settings to see matching player instructions.</p> : <>
      {loadingTimer && <p role="status" className="text-sm text-text-muted mb-2">Loading the complete saved requirements…</p>}
      {timerError && <p role="alert" className="text-warning text-sm mb-3">{timerError}</p>}
      <div className="flex flex-wrap gap-2 mb-3">
        <button type="button" className="btn-secondary" disabled={loadingTimer || !!timerError} onClick={() => {
          void (navigator.clipboard ? navigator.clipboard.writeText(instructions) : Promise.reject(new Error('Clipboard unavailable'))).then(() => setMessage('Instructions copied.')).catch(() => setMessage('Copy was unavailable. Select and copy the text below.'))
        }}><Icon name="Copy" size={14} />Copy instructions</button>
        <button type="button" className="btn-secondary" disabled={loadingTimer || !!timerError} onClick={() => {
          const url = URL.createObjectURL(new Blob([instructions], { type: 'text/plain;charset=utf-8' }))
          const link = document.createElement('a'); link.href = url; link.download = 'DST-player-compatibility.txt'; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
        }}><Icon name="Download" size={14} />Download instructions</button>
      </div>
      {message && <p role="status" className="mb-2 text-sm text-text-muted">{message}</p>}
      <pre className="text-xs text-text-muted whitespace-pre-wrap break-words rounded border border-border bg-surface-2 p-3">{instructions}</pre>
    </>}
  </section>
}
