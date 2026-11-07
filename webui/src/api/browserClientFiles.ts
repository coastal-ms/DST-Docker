import { api } from './client'
import type { GameConfigClientApplyItem, GameConfigClientApplyResult, GameConfigClientInfo, GameConfigRawUpdate } from './types'

type Key = 'game' | 'engine'
type Writer = { write(data: Blob | string | ArrayBuffer): Promise<void>; close(): Promise<void>; abort(): Promise<void> }
type Handle = { getFile(): Promise<File>; createWritable(): Promise<Writer> }
type Directory = { name: string; getFileHandle(name: string, options?: { create: boolean }): Promise<Handle>; getDirectoryHandle(name: string, options: { create: boolean }): Promise<Directory> }
type Snapshot = { raw: string; exists: boolean; file?: File }
type TimerChange = { enabled: boolean; seconds: string }
type Transform = { client: GameConfigClientInfo; changes: Partial<Record<Key, { before: string; after: string; created: boolean; applied: number }>>; applied: number; removed: number; download?: { filename: string; base64: string; files: number } | null }
let directory: Directory | null = null
let imported: Partial<Record<Key, File>> | null = null
let importedLabel = 'Selected client files'
let selectionRevision = 0
const names: Record<Key, string> = { game: 'Game.ini', engine: 'Engine.ini' }
const enginePreference = 'dst.browser-client-engine-enabled.v1'
const enabled = () => localStorage.getItem(enginePreference) === 'true'

async function readFiles(): Promise<Record<Key, Snapshot>> {
  const result = {} as Record<Key, Snapshot>
  for (const key of ['game', 'engine'] as const) {
    try {
      const file = directory ? await (await directory.getFileHandle(names[key])).getFile() : imported?.[key]
      if (!file) { result[key] = { raw: '', exists: false }; continue }
      if (file.size > 1024 * 1024) throw new Error(`${names[key]} is larger than 1 MiB.`)
      result[key] = { raw: await file.text(), exists: true, file }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'NotFoundError') result[key] = { raw: '', exists: false }
      else throw error
    }
  }
  return result
}

async function transform(mode: 'inspect' | 'apply' | 'disable-engine', before: Record<Key, Snapshot>, updates: GameConfigRawUpdate[] = [], reviewedRaw = false, engineEnabled = enabled(), download = false, timer?: TimerChange) {
  const files = Object.fromEntries(await Promise.all((['game', 'engine'] as const).map(async key => {
    const entry: { raw: string; exists: boolean; bytes?: string } = { raw: before[key].raw, exists: before[key].exists }
    if (download && before[key].file) {
      const bytes = new Uint8Array(await before[key].file!.arrayBuffer())
      let binary = ''
      for (let i = 0; i < bytes.length; i += 16384) binary += String.fromCharCode(...bytes.subarray(i, i + 16384))
      entry.bytes = btoa(binary)
    }
    return [key, entry]
  })))
  return api<Transform>('/api/docker/client-files/transform', { method: 'POST', body: JSON.stringify({
    mode: timer ? 'landclaim' : mode, selected: !!directory || !!imported, approved: mode !== 'inspect', directory: directory?.name ?? (imported ? importedLabel : ''), engineEnabled, reviewedRaw, updates, download, files,
    ...(timer ? { timerEnabled: timer.enabled, timerSeconds: timer.seconds } : {}),
  }) })
}

export function browserClientFolderSelected() { return directory !== null || imported !== null }
export function browserClientDeliveryMode() { return imported ? 'download' as const : 'folder' as const }

export async function selectBrowserClientFiles(files: File[], label = 'Selected client files') {
  const next: Partial<Record<Key, File>> = {}
  for (const file of files) {
    const key = (Object.keys(names) as Key[]).find(value => names[value].toLowerCase() === file.name.toLowerCase())
    if (!key || next[key]) throw new Error('Select only one Game.ini and one Engine.ini; do not select unrelated files.')
    if (file.size > 1024 * 1024) throw new Error(`${names[key]} is larger than 1 MiB.`)
    try { new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()) }
    catch { throw new Error(`${names[key]} must use UTF-8 text.`) }
    next[key] = file
  }
  if (!Object.keys(next).length) throw new Error('Select Game.ini or Engine.ini from your Dune client config folder.')
  directory = null; imported = next; importedLabel = label; selectionRevision++
  return getBrowserClientInfo()
}

export function isBrowserClientSelectionCancelled(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

async function chooseFiles(folder = false) {
  const input = document.createElement('input')
  input.type = 'file'; input.multiple = true
  if (folder) input.setAttribute('webkitdirectory', '')
  else input.accept = '.ini'
  input.style.display = 'none'; document.body.append(input)
  return new Promise<GameConfigClientInfo>((resolve, reject) => {
    let settled = false
    const cleanup = () => { input.remove() }
    const cancel = () => { if (settled) return; settled = true; cleanup(); reject(new DOMException('File selection cancelled.', 'AbortError')) }
    // Focus can return before a directory's files finish enumerating. Only
    // the browser's change/cancel events decide whether selection completed.
    input.addEventListener('change', () => {
      if (settled) return
      const selected = Array.from(input.files ?? [])
      if (!selected.length) { cancel(); return }
      settled = true; cleanup()
      const files = folder ? selected.filter(file => {
        const parts = (file.webkitRelativePath ?? '').split('/')
        return parts.length === 2 && Object.values(names).some(name => name.toLowerCase() === file.name.toLowerCase())
      }) : selected
      if (!files.length) { reject(new Error('Choose the client config folder containing Game.ini or Engine.ini directly, or use Choose files.')); return }
      const label = folder ? files[0].webkitRelativePath.split('/')[0] : undefined
      void selectBrowserClientFiles(files, label).then(resolve, reject)
    }, { once: true })
    input.addEventListener('cancel', cancel, { once: true })
    input.click()
  })
}

export function chooseBrowserClientFiles() { return chooseFiles() }

export async function chooseBrowserClientFolder() {
  const picker = (window as Window & { showDirectoryPicker?: (options: { mode: string; id: string }) => Promise<Directory> }).showDirectoryPicker
  if (!picker) return chooseFiles(true)
  let selected: Directory
  try { selected = await picker.call(window, { mode: 'readwrite', id: 'dst-client-config' }) }
  catch (error) {
    if (error instanceof DOMException && ['SecurityError', 'NotSupportedError'].includes(error.name)) return chooseFiles(true)
    throw error
  }
  // Confirm this is a game config directory before remembering the handle.
  let found = false
  for (const name of Object.values(names)) {
    try { await selected.getFileHandle(name); found = true } catch (error) { if (!(error instanceof DOMException && error.name === 'NotFoundError')) throw error }
  }
  if (!found) throw new Error('Choose the Dune config folder containing Game.ini or Engine.ini.')
  directory = selected; imported = null; selectionRevision++
  return getBrowserClientInfo()
}

export async function getBrowserClientInfo() {
  const client = (await transform('inspect', await readFiles())).client
  client.browserDelivery = imported ? 'download' : directory ? 'folder' : 'unselected'
  return client
}

function downloadPackage(result: Transform) {
  if (!Object.keys(result.changes).length) return false
  if (!result.download || result.download.filename !== 'DST-client-settings.zip') throw new Error('The reviewed client-file download was not prepared. No file was changed.')
  const bytes = Uint8Array.from(atob(result.download.base64), char => char.charCodeAt(0))
  const url = URL.createObjectURL(new Blob([bytes], { type: 'application/zip' }))
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = result.download.filename
  document.body.append(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  return true
}

async function assertUnchanged(before: Record<Key, Snapshot>, keys: Key[]) {
  const current = await readFiles()
  for (const key of keys) {
    if (current[key].exists !== before[key].exists || current[key].raw !== before[key].raw) throw new Error(`${names[key]} changed outside this review. Refresh your client files and review again.`)
    if (before[key].file && current[key].file) {
      const old = new Uint8Array(await before[key].file!.arrayBuffer()), fresh = new Uint8Array(await current[key].file!.arrayBuffer())
      if (old.length !== fresh.length || old.some((value, index) => value !== fresh[index])) throw new Error(`${names[key]} changed outside this review. Refresh your client files and review again.`)
    }
  }
}

async function write(handle: Handle, value: Blob | string | ArrayBuffer) {
  const writer = await handle.createWritable()
  try { await writer.write(value); await writer.close() } catch (error) { try { await writer.abort() } catch { /* keep the original failure */ } throw error }
}

async function saveTransformed(result: Transform, before: Record<Key, Snapshot>, selectedDirectory: Directory) {
  if (directory !== selectedDirectory) throw new Error('The selected client folder changed during review. Choose it again and review the changes.')
  const keys = Object.keys(result.changes) as Key[], backups: Partial<Record<Key, string>> = {}, saved: Key[] = []
  await assertUnchanged(before, keys)
  // Prepare every backup before changing either original file.
  if (keys.some(key => before[key].exists)) {
    const folder = await selectedDirectory.getDirectoryHandle('DST INI Backups', { create: true })
    for (const key of keys) if (before[key].file) {
      const name = `${names[key]}.${new Date().toISOString().replace(/[:.]/g, '-')}.${crypto.randomUUID()}.bak`
      const handle = await folder.getFileHandle(name, { create: true })
      await write(handle, before[key].file!)
      const actual = new Uint8Array(await (await handle.getFile()).arrayBuffer()), expected = new Uint8Array(await before[key].file!.arrayBuffer())
      if (actual.length !== expected.length || actual.some((value, index) => value !== expected[index])) throw new Error(`The ${names[key]} backup did not pass readback. No client file was changed.`)
      backups[key] = `DST INI Backups/${name}`
    }
  }
  try {
    for (const key of keys) {
      if (directory !== selectedDirectory) throw new Error('The selected client folder changed during review.')
      await assertUnchanged(before, [key])
      const handle = await selectedDirectory.getFileHandle(names[key], { create: true })
      let output: string | Blob = result.changes[key]!.after
      if (before[key].file) {
        const bytes = new Uint8Array(await before[key].file!.arrayBuffer())
        if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) output = new Blob([new Uint8Array([0xef, 0xbb, 0xbf]), output])
      }
      await write(handle, output); saved.push(key)
      if (await (await handle.getFile()).text() !== result.changes[key]!.after) throw new Error(`${names[key]} did not match after writing.`)
    }
  } catch (error) {
    throw new Error(`${error instanceof Error ? error.message : String(error)}${saved.length ? ` Already written: ${saved.map(key => names[key]).join(', ')}. Backups are in the selected folder; refresh and review before retrying.` : ''}`)
  }
  return backups
}

export async function applyBrowserClientSettings(updates: GameConfigRawUpdate[], validateOnly = false, reviewedRaw = true, timer?: TimerChange): Promise<GameConfigClientApplyResult> {
  if (!directory && !imported) throw new Error('Choose this PC’s client config folder or files before applying local changes.')
  if (imported) {
    const revision = selectionRevision, before = await readFiles()
    if (timer && !before.game.exists) throw new Error('Select the current Game.ini before preparing timer changes.')
    for (const update of updates) if (!before[update.file].exists) throw new Error(`Select the current ${names[update.file]} before preparing changes for it.`)
    const result = await transform('apply', before, updates, reviewedRaw, enabled(), !validateOnly, timer)
    if (revision !== selectionRevision) throw new Error('The selected client files changed during review. Review them again.')
    await assertUnchanged(before, Object.keys(result.changes) as Key[])
    const generated = !validateOnly && downloadPackage(result)
    return { ok: true, path: names.game, paths: names, backup: '', backups: {}, created: false, applied: 0,
      prepared: generated ? result.applied : 0, delivery: generated ? 'download' : 'validated',
      items: updates as GameConfigClientApplyItem[], client: await getBrowserClientInfo() }
  }
  if (!directory) throw new Error('Choose this PC’s client config folder before applying local changes.')
  const selectedDirectory = directory
  const before = await readFiles(), result = await transform('apply', before, updates, reviewedRaw, enabled(), false, timer)
  if (directory !== selectedDirectory) throw new Error('The selected client folder changed during review.')
  const backups = validateOnly ? {} : await saveTransformed(result, before, selectedDirectory)
  return { ok: true, path: names.game, paths: names, backup: backups.game ?? backups.engine ?? '', backups, created: false, applied: validateOnly ? 0 : result.applied,
    items: updates as GameConfigClientApplyItem[], client: validateOnly ? (await transform('inspect', before)).client : await getBrowserClientInfo() }
}

export function applyBrowserLandclaimTimer(enabled: boolean, seconds: string, validateOnly = false) {
  return applyBrowserClientSettings([], validateOnly, true, { enabled, seconds })
}

export async function setBrowserClientEngineEnabled(value: boolean) {
  if (!directory && !imported) throw new Error('Choose this PC’s client config folder or files before changing Engine.ini management.')
  let removed = 0
  let delivery: 'download' | undefined
  if (!value && imported) {
    const revision = selectionRevision, before = await readFiles(), result = await transform('disable-engine', before, [], true, false, true)
    if (revision !== selectionRevision) throw new Error('The selected client files changed during review.')
    await assertUnchanged(before, Object.keys(result.changes) as Key[])
    if (downloadPackage(result)) delivery = 'download'
    removed = result.removed
  }
  if (!value && directory) { const selectedDirectory = directory, before = await readFiles(), result = await transform('disable-engine', before, [], true, false); await saveTransformed(result, before, selectedDirectory); removed = result.removed }
  localStorage.setItem(enginePreference, String(value))
  return { ok: true, enabled: value, removed, delivery, client: await getBrowserClientInfo() }
}

export async function downloadBrowserClientFile(key: Key) {
  const files = await readFiles(), file = files[key].file
  if (!file) throw new Error(`Choose a folder containing ${names[key]} first.`)
  const url = URL.createObjectURL(file), anchor = document.createElement('a')
  anchor.href = url; anchor.download = names[key]; document.body.append(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  return { ok: true, path: names[key] }
}
