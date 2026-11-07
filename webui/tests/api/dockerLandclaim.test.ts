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
it('prevalidates the selected player file before saving and distinguishes download from installation', async () => {
  const result = await saveLandclaimTimer(true, '2.5', true)
  expect(apply.mock.calls).toEqual([[true, '2.5', true], [true, '2.5']])
  expect(apply.mock.invocationCallOrder[0]).toBeLessThan(request.mock.invocationCallOrder[0])
  expect(result.result.client).toMatchObject({ ok: true, applied: false, delivery: 'download' })
  expect(result.client.seconds).toBe('2.5')
})
it('does not touch the server when selected player-file validation fails', async () => {
  apply.mockRejectedValueOnce(new Error('Select the current Game.ini.'))
  await expect(saveLandclaimTimer(true, '2.5', true)).rejects.toThrow('Select the current Game.ini')
  expect(request).not.toHaveBeenCalled()
})
it('preserves the successful server outcome when the player write fails', async () => {
  apply.mockResolvedValueOnce({ ok: true }).mockRejectedValueOnce(new Error('Game.ini changed during review.'))
  const result = await saveLandclaimTimer(true, '2.5', true)
  expect(result.result.server.applied).toBe(true)
  expect(result.result.client).toMatchObject({ ok: false, applied: false, reason: 'Game.ini changed during review.' })
  expect(request.mock.calls.filter(([, options]) => options?.method === 'PUT')).toHaveLength(1)
})
it('reports a status-refresh failure without claiming that the completed server save failed', async () => {
  request.mockImplementationOnce(async () => ({ ...state, ok: true, result: { server: { ok: true, applied: true }, client: { ok: true, applied: false } } }))
    .mockRejectedValueOnce(new Error('Temporary reconnect'))
  const result = await saveLandclaimTimer(true, '2.5')
  expect(result.result.server.applied).toBe(true)
  expect(result.warning).toMatch(/server timer was saved/)
})
