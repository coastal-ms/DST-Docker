import { beforeEach, describe, expect, it, vi } from 'vitest'
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

beforeEach(() => { vi.resetModules(); request.mockReset(); localStorage.clear() })
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
