import { afterEach, beforeEach, expect, it, vi } from 'vitest'
const { request, apply, inspect } = vi.hoisted(() => ({ request: vi.fn(), apply: vi.fn(), inspect: vi.fn() }))
vi.mock('../../src/api/client', () => ({ api: request, withOnlinePlayerGuard: (fn: (force: boolean) => unknown) => fn(false) }))
vi.mock('../../src/api/browserClientFiles', () => ({ applyBrowserClientSettings: vi.fn(), applyBrowserLandclaimTimer: apply, downloadBrowserClientFile: vi.fn(), getBrowserClientInfo: inspect, setBrowserClientEngineEnabled: vi.fn() }))
import { saveLandclaimTimer } from '../../src/api/gameconfig'
const state = { server: { available: true, enabled: true, seconds: '2.5', formattedOk: true }, client: { exists: false, dirExists: false, path: 'Game.ini', dir: '', enabled: false, seconds: '', formattedOk: false }, clientBlock: 'fixture' }
beforeEach(() => {
  vi.stubEnv('VITE_DST_EDITION', 'docker')
  request.mockImplementation(async (_path, options) => options ? { ...state, ok: true, result: { ok: true, server: { ok: true, applied: true }, client: { ok: true, applied: false } } } : state)
  inspect.mockResolvedValue({ game: { exists: true, path: 'Game.ini' }, dirExists: true, dir: 'Selected files', landclaimTimer: { enabled: true, seconds: '2.5', formattedOk: true }, browserDelivery: 'download' })
  apply.mockResolvedValue({ ok: true, applied: 0, delivery: 'download' })
})
afterEach(() => { vi.clearAllMocks(); vi.unstubAllEnvs() })
it('keeps a server-only timer save independent of player files', async () => {
  const result = await saveLandclaimTimer(true, '2.5')
  expect(apply).not.toHaveBeenCalled()
  expect(request).toHaveBeenCalledWith('/api/gameconfig/landclaim-timer', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ enabled: true, seconds: '2.5' }) }))
  expect(result.server.seconds).toBe('2.5')
})
it('loads saved manual snippets without inspecting player files', async () => {
  const { getLandclaimTimer } = await import('../../src/api/gameconfig')
  expect((await getLandclaimTimer()).clientBlock).toBe('fixture')
  expect(inspect).not.toHaveBeenCalled()
  expect(apply).not.toHaveBeenCalled()
})
it('keeps server validation errors visible without touching player files', async () => {
  request.mockRejectedValueOnce(new Error('Server settings changed'))
  await expect(saveLandclaimTimer(true, '2.5')).rejects.toThrow('Server settings changed')
  expect(inspect).not.toHaveBeenCalled()
  expect(apply).not.toHaveBeenCalled()
})
