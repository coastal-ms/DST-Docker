import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GameConfigClientInfo } from '../src/api/types'
const request = vi.hoisted(() => vi.fn())
vi.mock('../src/api/client', () => ({ api: request }))

function client(raw = '') {
  const file = { file: 'game', path: 'Game.ini', exists: true, raw, sections: [], effective: {}, managedSections: [] }
  return { ...file, dir: 'Windows', dirResolved: 'Windows', dirExists: true, default: '', engineEnabled: true, game: file, engine: { ...file, file: 'engine', path: 'Engine.ini' } } as GameConfigClientInfo
}
function fixture() {
  const files = new Map<string, string>([['Game.ini', '[Manual]\nKeep=original\n'], ['Engine.ini', '[ConsoleVariables]\nVehicle.MaxVehiclesPerPlayer=10\n']])
  const backups = new Map<string, string>(), events: string[] = []
  const snapshot = (raw: string) => {
    const bytes = new TextEncoder().encode(raw)
    return { size: bytes.length, text: async () => raw, arrayBuffer: async () => bytes.buffer } as File
  }
  function handle(name: string, collection: Map<string, string>) {
    return {
      getFile: async () => snapshot(collection.get(name) ?? ''),
      createWritable: async () => {
        let data = ''
        return {
          write: async (value: string | File) => { data = typeof value === 'string' ? value : await value.text() },
          close: async () => { collection.set(name, data); events.push(`${collection === files ? 'write' : 'backup'}:${name}`) },
          abort: async () => { events.push(`abort:${name}`) },
        }
      },
    }
  }
  const backupFolder = { name: 'DST INI Backups', getFileHandle: async (name: string) => handle(name, backups) }
  const directory = {
    name: 'Windows',
    getFileHandle: async (name: string, options?: { create: boolean }) => {
      if (!files.has(name) && !options?.create) throw new DOMException('Missing', 'NotFoundError')
      return handle(name, files)
    },
    getDirectoryHandle: async () => backupFolder,
  }
  return { directory, files, backups, events }
}

beforeEach(() => {
  vi.resetModules(); request.mockReset(); localStorage.clear()
  Object.defineProperty(window, 'showDirectoryPicker', { configurable: true, value: undefined })
})
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers() })
describe('Browser-selected player files', () => {
  it('projects an unselected browser without using native client endpoints or writing files', async () => {
    request.mockImplementation(async (path, init) => { const body = JSON.parse(init.body); expect(path).toBe('/api/docker/client-files/transform'); expect(body.selected).toBe(false); return { client: { ...client(), dirExists: false } } })
    const module = await import('../src/api/browserClientFiles')
    expect((await module.getBrowserClientInfo()).dirExists).toBe(false)
    await expect(module.applyBrowserClientSettings([])).rejects.toThrow('Choose this PC')
  })

  it('validates without writing, then backs up the exact original before applying and reading back', async () => {
    const f = fixture()
    Object.defineProperty(window, 'showDirectoryPicker', { configurable: true, value: vi.fn(async () => f.directory) })
    request.mockImplementation(async (_path, init) => {
      const body = JSON.parse(init.body)
      return { client: client(body.files.game.raw), applied: 1, changes: body.mode === 'apply' ? { engine: { before: body.files.engine.raw, after: '[ConsoleVariables]\nVehicle.MaxVehiclesPerPlayer=20\n', created: false, applied: 1 } } : {} }
    })
    const module = await import('../src/api/browserClientFiles')
    await module.chooseBrowserClientFolder()
    const updates = [{ file: 'engine' as const, section: 'ConsoleVariables', key: 'Vehicle.MaxVehiclesPerPlayer', value: '20' }]
    await module.applyBrowserClientSettings(updates, true)
    expect(f.events).toEqual([])
    const original = f.files.get('Engine.ini')
    await module.applyBrowserClientSettings(updates)
    expect(f.backups.size).toBe(1); expect([...f.backups.values()][0]).toBe(original)
    expect(f.events[0]).toMatch(/^backup:/); expect(f.events[1]).toBe('write:Engine.ini')
    expect(f.files.get('Game.ini')).toBe('[Manual]\nKeep=original\n')
    expect(f.files.get('Engine.ini')).toContain('=20')
  })

  it('refuses a manual edit made while the transform is in flight', async () => {
    const f = fixture()
    Object.defineProperty(window, 'showDirectoryPicker', { configurable: true, value: vi.fn(async () => f.directory) })
    request.mockImplementation(async (_path, init) => {
      const body = JSON.parse(init.body)
      if (body.mode === 'apply') f.files.set('Engine.ini', '[Manual]\nDoNotOverwrite=yes\n')
      return { client: client(), applied: 1, changes: body.mode === 'apply' ? { engine: { before: body.files.engine.raw, after: 'desired', created: false, applied: 1 } } : {} }
    })
    const module = await import('../src/api/browserClientFiles'); await module.chooseBrowserClientFolder()
    await expect(module.applyBrowserClientSettings([{ file: 'engine', section: 'ConsoleVariables', key: 'Vehicle.MaxVehiclesPerPlayer', value: '20' }])).rejects.toThrow('changed outside this review')
    expect(f.events).toEqual([]); expect(f.files.get('Engine.ini')).toContain('DoNotOverwrite=yes')
  })
})

function selectedFile(name: string, text: string, bom = false) {
  const content = new TextEncoder().encode(text)
  const bytes = bom ? new Uint8Array([239, 187, 191, ...content]) : content
  return { name, size: bytes.length, text: async () => new TextDecoder().decode(bytes), arrayBuffer: async () => bytes.slice().buffer } as File
}

describe('Portable browser client downloads', () => {
  it('opens a folder picker without secure directory handles and reads only its direct client INIs', async () => {
    vi.useFakeTimers()
    request.mockImplementation(async (_path, init) => {
      const body = JSON.parse(init.body)
      expect(body.mode).toBe('inspect'); expect(body.directory).toBe('WindowsClient')
      expect(body.files.game.raw).toBe('[Manual]\nKeep=original\n')
      return { client: client(body.files.game.raw), changes: {} }
    })
    const module = await import('../src/api/browserClientFiles')
    const result = module.chooseBrowserClientFolder()
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!
    expect(input.hasAttribute('webkitdirectory')).toBe(true)
    window.dispatchEvent(new Event('focus'))
    await vi.advanceTimersByTimeAsync(2000)
    expect(input.isConnected).toBe(true)
    const entries = [
      ['Game.ini', 'WindowsClient/Game.ini', '[Manual]\nKeep=original\n'],
      ['Engine.ini', 'WindowsClient/Engine.ini', '[ConsoleVariables]\n'],
      ['Input.ini', 'WindowsClient/Input.ini', 'unrelated'],
      ['Game.ini', 'WindowsClient/Backups/Game.ini', 'old backup'],
    ].map(([name, path, raw]) => Object.assign(selectedFile(name, raw), { webkitRelativePath: path }))
    Object.defineProperty(input, 'files', { value: entries })
    input.dispatchEvent(new Event('change'))
    expect((await result).browserDelivery).toBe('download')
    expect(request).toHaveBeenCalledOnce()
    expect(document.querySelector('input[type="file"]')).toBeNull()
  })

  it('offers a separate file picker and keeps the existing selection when a new picker is cancelled', async () => {
    request.mockResolvedValue({ client: client(), changes: {} })
    const module = await import('../src/api/browserClientFiles')
    await module.selectBrowserClientFiles([selectedFile('Game.ini', 'retained original')])
    const result = module.chooseBrowserClientFiles()
    const rejected = expect(result).rejects.toMatchObject({ name: 'AbortError' })
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!
    expect(input.hasAttribute('webkitdirectory')).toBe(false)
    input.dispatchEvent(new Event('cancel'))
    await rejected
    expect(module.browserClientFolderSelected()).toBe(true)
  })
  it('uses the dedicated timer transform for a reviewed download and requires the selected Game.ini', async () => {
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:fixture') })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    request.mockImplementation(async (_path, init) => {
      const body = JSON.parse(init.body)
      if (body.mode === 'landclaim') {
        expect(body).toMatchObject({ timerEnabled: true, timerSeconds: '2.5', approved: true, download: true, updates: [] })
        expect(body.files.game.bytes).toBeTruthy()
        return { client: client(), applied: 2, changes: { game: { after: 'updated timer' } }, download: { filename: 'DST-client-settings.zip', base64: btoa('fixture'), files: 1 } }
      }
      return { client: client(body.files.game.raw), changes: {} }
    })
    const module = await import('../src/api/browserClientFiles')
    await module.selectBrowserClientFiles([selectedFile('Engine.ini', '[Manual]\nKeep=yes')])
    await expect(module.applyBrowserLandclaimTimer(true, '2.5')).rejects.toThrow('Select the current Game.ini')
    await module.selectBrowserClientFiles([selectedFile('Game.ini', '[Manual]\nKeep=original')])
    expect(await module.applyBrowserLandclaimTimer(true, '2.5')).toMatchObject({ applied: 0, prepared: 2, delivery: 'download' })
  })
  it('prepares a download with exact original bytes and never reports an installed change', async () => {
    const original = selectedFile('Game.ini', '[Manual]\r\nKeep=original\r\n', true)
    const create = vi.fn(() => 'blob:fixture')
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: create })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    request.mockImplementation(async (_path, init) => {
      const body = JSON.parse(init.body)
      if (body.mode === 'apply') {
        expect(body.download).toBe(true)
        expect(body.files.game.bytes).toBe(btoa(String.fromCharCode(...new Uint8Array(await original.arrayBuffer()))))
        return { client: client('changed'), applied: 1, changes: { game: { after: 'changed' } }, download: { filename: 'DST-client-settings.zip', base64: btoa('zip fixture'), files: 1 } }
      }
      return { client: client(body.files.game.raw), changes: {} }
    })
    const module = await import('../src/api/browserClientFiles')
    const info = await module.selectBrowserClientFiles([original])
    expect(info.browserDelivery).toBe('download')
    const result = await module.applyBrowserClientSettings([{ file: 'game', section: 'Manual', key: 'Keep', value: 'changed' }])
    expect(result).toMatchObject({ applied: 0, prepared: 1, delivery: 'download' })
    expect(result.client.raw).toContain('Keep=original')
    expect(await original.text()).toContain('Keep=original')
    expect(create).toHaveBeenCalledOnce(); expect(click).toHaveBeenCalledOnce()
  })

  it('requires the original for each changed file instead of inventing an unselected file', async () => {
    request.mockResolvedValue({ client: client(), changes: {} })
    const module = await import('../src/api/browserClientFiles')
    await module.selectBrowserClientFiles([selectedFile('Game.ini', '[Manual]\nKeep=original')])
    const count = request.mock.calls.length
    await expect(module.applyBrowserClientSettings([{ file: 'engine', section: 'ConsoleVariables', key: 'Vehicle.MaxVehiclesPerPlayer', value: '20' }])).rejects.toThrow('Select the current Engine.ini')
    expect(request).toHaveBeenCalledTimes(count)
  })

  it('rejects unrelated, duplicate, oversized and invalid-UTF8 selections before upload', async () => {
    const module = await import('../src/api/browserClientFiles')
    for (const files of [
      [selectedFile('passwords.ini', 'not a client INI')],
      [selectedFile('Game.ini', 'a'), selectedFile('GAME.INI', 'b')],
      [{ ...selectedFile('Game.ini', 'a'), size: 1024 * 1024 + 1 } as File],
      [{ ...selectedFile('Game.ini', 'a'), arrayBuffer: async () => new Uint8Array([255]).buffer } as File],
    ]) await expect(module.selectBrowserClientFiles(files)).rejects.toThrow()
    expect(request).not.toHaveBeenCalled()
  })

  it('blocks a download if selection changes while its reviewed transform is in flight', async () => {
    const module = await import('../src/api/browserClientFiles')
    request.mockImplementation(async (_path, init) => {
      const body = JSON.parse(init.body)
      if (body.mode === 'apply') await module.selectBrowserClientFiles([selectedFile('Game.ini', 'new selection')])
      return { client: client(), applied: 1, changes: body.mode === 'apply' ? { game: { after: 'changed' } } : {} }
    })
    await module.selectBrowserClientFiles([selectedFile('Game.ini', 'original')])
    await expect(module.applyBrowserClientSettings([{ file: 'game', section: 'Manual', key: 'Keep', value: 'changed' }])).rejects.toThrow('selected client files changed')
  })

  it('cancels a normal file picker without leaving its input behind', async () => {
    const module = await import('../src/api/browserClientFiles')
    const result = module.chooseBrowserClientFolder()
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!
    expect(input).not.toBeNull()
    input.dispatchEvent(new Event('cancel'))
    await expect(result).rejects.toThrow('cancelled')
    expect(document.querySelector('input[type="file"]')).toBeNull()
  })
})
