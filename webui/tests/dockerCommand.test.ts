import { afterEach, expect, it, vi } from 'vitest'
import { completeDockerCommand } from '../src/api/dockerCommand'

const request = vi.hoisted(() => ({ api: vi.fn(), navigation: vi.fn((path: string) => path + '?t=fixture') }))
vi.mock('../src/api/client', () => ({ api: request.api, authenticatedApiNavigation: request.navigation }))
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); request.api.mockReset(); request.navigation.mockClear() })

it('downloads only the completed correlated archive and reports partial collection', async () => {
  vi.useFakeTimers()
  request.api.mockResolvedValue({ state: { operation: { id: 'own', phase: 'completed', result: { downloadId: 'a'.repeat(32), complete: false } } } })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  const pending = completeDockerCommand('own')
  await vi.advanceTimersByTimeAsync(2000)
  await expect(pending).resolves.toEqual({ downloaded: true, complete: false })
  expect(request.navigation).toHaveBeenCalledWith('/api/docker/log-exports/' + 'a'.repeat(32))
  expect(click).toHaveBeenCalledTimes(1)
  expect(document.querySelector('a[download]')).toBeNull()
})

it('rejects changed operations and never downloads an unrelated result', async () => {
  vi.useFakeTimers()
  request.api.mockResolvedValue({ state: { operation: { id: 'different', phase: 'completed', result: { downloadId: 'a'.repeat(32) } } } })
  const pending = expect(completeDockerCommand('own')).rejects.toThrow('operation changed')
  await vi.advanceTimersByTimeAsync(2000)
  await pending
  expect(request.navigation).not.toHaveBeenCalled()
})

it('rejects failed collection without issuing a download or replaying the export', async () => {
  vi.useFakeTimers()
  request.api.mockResolvedValue({ state: { operation: { id: 'own', phase: 'failed', error: 'Logs unavailable' } } })
  const pending = expect(completeDockerCommand('own')).rejects.toThrow('Logs unavailable')
  await vi.advanceTimersByTimeAsync(2000)
  await pending
  expect(request.api).toHaveBeenCalledTimes(1)
  expect(request.navigation).not.toHaveBeenCalled()
})
