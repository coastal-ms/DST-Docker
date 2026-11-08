import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../src/api/client'
import { completeDockerCommand } from '../src/api/dockerCommand'
import { buildDiagnosticBundle } from '../src/api/diagnostics'
import { renameServer } from '../src/api/server'

vi.mock('../src/api/client', () => ({ api: vi.fn() }))
vi.mock('../src/api/dockerCommand', () => ({ completeDockerCommand: vi.fn() }))
afterEach(() => { vi.clearAllMocks(); vi.unstubAllEnvs() })

it('follows the native export identity before reporting a downloaded package', async () => {
  vi.stubEnv('VITE_DST_EDITION', 'docker')
  vi.mocked(api).mockResolvedValue({ ok: true, operationId: 'a'.repeat(32) } as never)
  vi.mocked(completeDockerCommand).mockResolvedValue({ downloaded: true, complete: false })
  const result = await buildDiagnosticBundle()
  expect(completeDockerCommand).toHaveBeenCalledWith('a'.repeat(32))
  expect(result.browserDownload).toBe(true)
  expect(result.warnings).toEqual([expect.stringContaining('export-report.json')])
})

it('does not report success without a prepared browser download', async () => {
  vi.stubEnv('VITE_DST_EDITION', 'docker')
  vi.mocked(api).mockResolvedValue({ ok: true, operationId: 'a'.repeat(32) } as never)
  vi.mocked(completeDockerCommand).mockResolvedValue({ downloaded: false, complete: true })
  await expect(buildDiagnosticBundle()).rejects.toThrow('download was not prepared')
})

it('preserves the existing Windows bundle response', async () => {
  vi.stubEnv('VITE_DST_EDITION', '')
  const bundle = { ok: true, path: 'existing.zip', fileCount: 2, sizeBytes: 200, sanitized: true, warnings: [] }
  vi.mocked(api).mockResolvedValue(bundle as never)
  expect(await buildDiagnosticBundle()).toEqual(bundle)
  expect(completeDockerCommand).not.toHaveBeenCalled()
})

it('waits for the existing Docker rename operation instead of reporting an accepted request as completed', async () => {
  vi.stubEnv('VITE_DST_EDITION', 'docker')
  vi.mocked(api).mockResolvedValue({ ok: true, newName: 'After', operationId: 'b'.repeat(32) } as never)
  vi.mocked(completeDockerCommand).mockResolvedValue({ downloaded: false, complete: true })
  expect((await renameServer('After')).newName).toBe('After')
  expect(completeDockerCommand).toHaveBeenCalledWith('b'.repeat(32))
})
