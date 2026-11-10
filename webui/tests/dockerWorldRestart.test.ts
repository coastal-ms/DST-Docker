import { afterEach, beforeEach, expect, it, vi } from 'vitest'
const { request } = vi.hoisted(() => ({ request: vi.fn() }))
vi.mock('../src/api/client', () => ({ api: request, withOnlinePlayerGuard: vi.fn(() => { throw new Error('Docker must use native offline checks') }) }))
import { getWorldRestartStatus, startWorldRestart, rollbackWorldRestart, resumeDockerWorldRestart, getWorldRestartResearchAudit, recoverWorldRestartResearch, rollbackWorldRestartResearch } from '../src/api/database'
beforeEach(() => { vi.stubEnv('VITE_DST_EDITION', 'docker'); request.mockReset() })
afterEach(() => vi.unstubAllEnvs())

it('uses owner-protected native status and exact reset confirmations without VM routes', async () => {
  const status = { phase: 'idle', running: false, steps: [] }
  request.mockResolvedValue({ ok: true, data: { worldRestart: status } })
  expect(await getWorldRestartStatus()).toEqual(status)
  await startWorldRestart('RESTART WORLD'); await rollbackWorldRestart('ROLL BACK WORLD'); await resumeDockerWorldRestart()
  expect(request.mock.calls.map(call => call[0])).toEqual(Array(4).fill('/api/docker/setup'))
  expect(request.mock.calls.slice(1).map(call => JSON.parse(call[1].body))).toEqual([
    { action: 'world-restart.apply', confirmation: 'RESTART WORLD' },
    { action: 'world-restart.rollback', confirmation: 'ROLL BACK WORLD' },
    { action: 'world-restart.recover' },
  ])
})

it('keeps research evidence and recovery bounded to a selected character and captured keys', async () => {
  request.mockResolvedValue({ ok: true, data: { available: true, mismatches: [] } })
  expect((await getWorldRestartResearchAudit()).available).toBe(true)
  const accepted = await recoverWorldRestartResearch({ characterName: 'Fixture', funcomId: 'fixture-id', itemKeys: ['RCP_Fixture'], confirm: 'RESET RESEARCH' })
  expect(accepted.message).toContain('started'); expect(accepted).not.toHaveProperty('backupSizeBytes')
  expect(JSON.parse(request.mock.calls[1][1].body)).toEqual({ action: 'world-restart.research', confirmation: 'RESET RESEARCH', characterName: 'Fixture', funcomId: 'fixture-id', itemKeys: ['RCP_Fixture'] })
  await expect(rollbackWorldRestartResearch('wrong')).rejects.toThrow('exactly')
  expect(request).toHaveBeenCalledTimes(2)
})

it('surfaces native manager refusal and unavailable status', async () => {
  request.mockResolvedValue({ ok: false, error: 'Keep players offline.' })
  await expect(startWorldRestart('RESTART WORLD')).rejects.toThrow('Keep players offline.')
  request.mockResolvedValue({ ok: true, data: {} })
  await expect(getWorldRestartStatus()).rejects.toThrow('status is unavailable')
})
