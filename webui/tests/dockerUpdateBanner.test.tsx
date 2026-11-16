import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { DockerUpdateBanner } from '../src/components/DockerUpdateBanner'
import { DockerProductUpdateCard } from '../src/pages/docker/DockerProductUpdateCard'
import { publishDockerProductUpdate } from '../src/hooks/useDockerProductUpdate'
import { api } from '../src/api/client'
import { BrowserRouter } from '../src/router'

vi.mock('../src/api/client', () => ({ api: vi.fn() }))
const current = { supported: true, available: false, currentVersion: '1.0.14', latestVersion: '1.0.14' }
const newer = { ...current, available: true, latestVersion: '1.0.15', tag: 'v1.0.15', commit: 'fixture' }
afterEach(() => { cleanup(); sessionStorage.clear(); vi.clearAllMocks(); vi.useRealTimers() })
function show(card = false) {
  return render(<BrowserRouter><DockerUpdateBanner />{card && <DockerProductUpdateCard />}</BrowserRouter>)
}
it('checks Docker on portal entry and links a discovered update to Settings without starting an installer', async () => {
  vi.mocked(api).mockResolvedValue(newer)
  show()
  const link = await screen.findByRole('link', { name: 'View update' })
  expect(link.getAttribute('href')).toContain('/settings?section=settings.docker-updates')
  expect(screen.getByText('DST Docker update available:')).toBeTruthy()
  expect(vi.mocked(api).mock.calls.every(([path, init]) => path === '/api/docker/product-update' && !init?.method)).toBe(true)
})
it('shares manual checks with the banner and clears it when the installed version is current', async () => {
  vi.mocked(api).mockImplementation(async path => path.includes('force=1') ? newer : current)
  show(true)
  await waitFor(() => expect(screen.getByText('You have this or a newer version.')).toBeTruthy())
  expect(screen.queryByRole('link', { name: 'View update' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Check now' }))
  await screen.findByRole('link', { name: 'View update' })
  act(() => publishDockerProductUpdate(current))
  expect(screen.queryByRole('link', { name: 'View update' })).toBeNull()
})
it('dismisses only the current release and shows a later release in the same session', async () => {
  vi.mocked(api).mockResolvedValue(newer)
  show()
  await screen.findByRole('link', { name: 'View update' })
  fireEvent.click(screen.getByRole('button', { name: 'Later' }))
  expect(screen.queryByRole('link', { name: 'View update' })).toBeNull()
  act(() => publishDockerProductUpdate({ ...newer, latestVersion: '1.0.16' }))
  expect(screen.getByRole('link', { name: 'View update' })).toBeTruthy()
})
it('checks again automatically after six hours', async () => {
  vi.mocked(api).mockResolvedValue(current)
  show()
  await waitFor(() => expect(screen.queryByRole('link', { name: 'View update' })).toBeNull())
  vi.useFakeTimers()
  // Mount again with fake timers so the shared subscription owns a controlled timer.
  cleanup()
  show()
  await act(async () => { await Promise.resolve() })
  expect(screen.queryByRole('link', { name: 'View update' })).toBeNull()
  vi.mocked(api).mockResolvedValue(newer)
  vi.mocked(api).mockClear()
  await act(async () => { await vi.advanceTimersByTimeAsync(6 * 60 * 60 * 1000) })
  expect(api).toHaveBeenCalledWith('/api/docker/product-update')
  expect(screen.getByRole('link', { name: 'View update' })).toBeTruthy()
})
it('keeps failed checks quiet', async () => {
  vi.mocked(api).mockResolvedValue({ ...current, error: 'Offline' })
  show()
  await act(async () => { await Promise.resolve() })
  expect(screen.queryByRole('link', { name: 'View update' })).toBeNull()
  expect(screen.queryByText('Offline')).toBeNull()
})
