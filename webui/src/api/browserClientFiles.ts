import { api } from './client'
import type { GameConfigClientApplyItem, GameConfigClientApplyResult, GameConfigClientInfo, GameConfigRawUpdate } from './types'

type Key = 'game' | 'engine'
type Writer = { write(data: Blob | string | ArrayBuffer): Promise<void>; close(): Promise<void>; abort(): Promise<void> }
type Handle = { getFile(): Promise<File>; createWritable(): Promise<Writer> }
type Directory = { name: string; getFileHandle(name: string, options?: { create: boolean }): Promise<Handle>; getDirectoryHandle(name: string, options: { create: boolean }): Promise<Directory> }
type Snapshot = { raw: string; exists: boolean; file?: File }
type Transform = { client: GameConfigClientInfo; changes: Partial<Record<Key, { before: string; after: string; created: boolean; applied: number }>>; applied: number; removed: number }
let directory: Directory | null = null
const names: Record<Key, string> = { game: 'Game.ini', engine: 'Engine.ini' }
const enginePreference = 'dst.browser-client-engine-enabled.v1'
const enabled = () => localStorage.getItem(enginePreference) === 'true'

async function readFiles(): Promise<Record<Key, Snapshot>> {
  const result = {} as Record<Key, Snapshot>
  for (const key of ['game', 'engine'] as const) {
    try {
      if (!directory) { result[key] = { raw: '', exists: false }; continue }
      const handle = await directory.getFileHandle(names[key])
      const file = await handle.getFile()
      if (file.size > 1024 * 1024) throw new Error(`${names[key]} is larger than 1 MiB.`)
      result[key] = { raw: await file.text(), exists: true, file }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'NotFoundError') result[key] = { raw: '', exists: false }
      else throw error
    }
  }
  return result
}

async function transform(mode: 'inspect' | 'apply' | 'disable-engine', before: Record<Key, Snapshot>, updates: GameConfigRawUpdate[] = [], reviewedRaw = false, engineEnabled = enabled()) {
  return api<Transform>('/api/docker/client-files/transform', { method: 'POST', body: JSON.stringify({
    mode, selected: !!directory, approved: mode !== 'inspect', directory: directory?.name ?? '', engineEnabled, reviewedRaw, updates,
    files: Object.fromEntries((['game', 'engine'] as const).map(key => [key, { raw: before[key].raw, exists: before[key].exists }])),
  }) })
}

export function browserClientFolderSelected() { return directory !== null }

export async function chooseBrowserClientFolder() {
  const picker = (window as Window & { showDirectoryPicker?: (options: { mode: string; id: string }) => Promise<Directory> }).showDirectoryPicker
  if (!picker) throw new Error('This browser cannot write a selected folder. Open this local portal in Chrome or Edge to choose client files. Server settings can still be saved separately.')
  const selected = await picker.call(window, { mode: 'readwrite', id: 'dst-client-config' })
  // Confirm this is a game config directory before remembering the handle.
  let found = false
  for (const name of Object.values(names)) {
    try { await selected.getFileHandle(name); found = true } catch (error) { if (!(error instanceof DOMException && error.name === 'NotFoundError')) throw error }
  }
  if (!found) throw new Error('Choose the Dune config folder containing Game.ini or Engine.ini.')
  directory = selected
  return getBrowserClientInfo()
}

export async function getBrowserClientInfo() { return (await transform('inspect', await readFiles())).client }

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

export async function applyBrowserClientSettings(updates: GameConfigRawUpdate[], validateOnly = false, reviewedRaw = true): Promise<GameConfigClientApplyResult> {
  if (!directory) throw new Error('Choose this PC’s client config folder before applying local changes.')
  const selectedDirectory = directory
  const before = await readFiles(), result = await transform('apply', before, updates, reviewedRaw)
  if (directory !== selectedDirectory) throw new Error('The selected client folder changed during review.')
  const backups = validateOnly ? {} : await saveTransformed(result, before, selectedDirectory)
  return { ok: true, path: names.game, paths: names, backup: backups.game ?? backups.engine ?? '', backups, created: false, applied: validateOnly ? 0 : result.applied,
    items: updates as GameConfigClientApplyItem[], client: validateOnly ? (await transform('inspect', before)).client : await getBrowserClientInfo() }
}

export async function setBrowserClientEngineEnabled(value: boolean) {
  if (!directory) throw new Error('Choose this PC’s client config folder before changing Engine.ini management.')
  let removed = 0
  if (!value && directory) { const selectedDirectory = directory, before = await readFiles(), result = await transform('disable-engine', before, [], true, false); await saveTransformed(result, before, selectedDirectory); removed = result.removed }
  localStorage.setItem(enginePreference, String(value))
  return { ok: true, enabled: value, removed, client: await getBrowserClientInfo() }
}

export async function downloadBrowserClientFile(key: Key) {
  const files = await readFiles(), file = files[key].file
  if (!file) throw new Error(`Choose a folder containing ${names[key]} first.`)
  const url = URL.createObjectURL(file), anchor = document.createElement('a')
  anchor.href = url; anchor.download = names[key]; document.body.append(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  return { ok: true, path: names[key] }
}
