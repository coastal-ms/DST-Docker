import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../src/api/client'
import { MemorySwapControl } from '../src/components/MemorySwapControl'

const access = vi.hoisted(() => ({ owner: true }))
vi.mock('../src/api/client', () => ({ api: vi.fn() }))
vi.mock('../src/auth/portalAccess', () => ({ usePortalAccess: () => ({ canAccessOwnerSurfaces: access.owner }) }))
const status = { available: true, enabled: false, perServerGiB: 2, poolGiB: 0, configuredSwappiness: 10, existingSwapGiB: 10, worldServerCount: 2, safeAvailableDiskGiB: 50, hostPoolActive: false, swappiness: 60, pending: false, operation: { id: 'old', phase: 'completed' } }
beforeEach(() => { access.owner = true; vi.mocked(api).mockReset(); vi.spyOn(window, 'confirm').mockReturnValue(true) })
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('Docker Memory Swap', () => {
  it('uses existing host swap and reviews the automatic policy before sending a typed operation', async () => {
    vi.mocked(api).mockResolvedValueOnce(status)
      .mockResolvedValueOnce({ ok: true, data: { operation: { id: 'swap-op' } } })
      .mockResolvedValueOnce({ ...status, enabled: true, operation: { id: 'swap-op', phase: 'completed' } })
    render(<MemorySwapControl />)
    fireEvent.click(await screen.findByRole('button', { name: 'Memory Swap: Off' }))
    fireEvent.click(screen.getByRole('button', { name: 'Enable Memory Swap' }))
    await waitFor(() => expect(screen.getByText(/Memory Swap saved and verified/)).toBeInTheDocument())
    const options = vi.mocked(api).mock.calls.find(([path, value]) => path === '/api/docker/memory-swap' && value?.method === 'PUT')?.[1]
    expect(JSON.parse(String(options?.body))).toEqual({ enabled: true, perServerGiB: 2, poolGiB: 0, swappiness: 10, confirmation: 'ENABLE MEMORY SWAP' })
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('Map RAM limits stay unchanged'))
  })

  it('does not start a host operation when the review is cancelled', async () => {
    vi.mocked(api).mockResolvedValue(status); vi.mocked(window.confirm).mockReturnValue(false)
    render(<MemorySwapControl />)
    fireEvent.click(await screen.findByRole('button', { name: 'Memory Swap: Off' }))
    fireEvent.click(screen.getByRole('button', { name: 'Enable Memory Swap' }))
    expect(api).toHaveBeenCalledTimes(1)
  })

  it('restores the previous recorded policy after an interrupted change', async () => {
    vi.mocked(api).mockResolvedValueOnce({ ...status, pending: true, pendingChange: { error: 'Host pool needs recovery.' }, operation: { id: 'old', phase: 'failed' } })
      .mockResolvedValueOnce({ ok: true, data: { operation: { id: 'recover-op' } } })
      .mockResolvedValueOnce({ ...status, operation: { id: 'recover-op', phase: 'completed' } })
    render(<MemorySwapControl />)
    fireEvent.click(await screen.findByRole('button', { name: 'Memory Swap: Off' }))
    fireEvent.click(screen.getByRole('button', { name: 'Restore previous swap policy' }))
    await screen.findByText('Memory Swap recovery completed.')
    expect(api).toHaveBeenCalledWith('/api/docker/memory-swap/recover', { method: 'POST', body: JSON.stringify({ restorePrevious: true, confirmation: 'RECOVER MEMORY SWAP' }) })
  })

  it('keeps host controls and host observations unavailable to non-owners', () => {
    access.owner = false; render(<MemorySwapControl />)
    expect(screen.queryByRole('region', { name: 'Memory Swap controls' })).not.toBeInTheDocument()
    expect(api).not.toHaveBeenCalled()
  })

  it('preserves an actionable preflight error after refreshing unchanged status', async () => {
    vi.mocked(api).mockResolvedValueOnce(status)
      .mockResolvedValueOnce({ ok: true, data: { operation: { id: 'failed-op' } } })
      .mockResolvedValueOnce({ ...status, operation: { id: 'failed-op', phase: 'failed', error: 'Host swap accounting is unavailable.' } })
      .mockResolvedValueOnce({ ...status, operation: { id: 'failed-op', phase: 'failed' } })
    render(<MemorySwapControl />)
    fireEvent.click(await screen.findByRole('button', { name: 'Memory Swap: Off' }))
    fireEvent.click(screen.getByRole('button', { name: 'Enable Memory Swap' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Host swap accounting is unavailable.')
  })

  it('offers an explicit default restoration for maps with legacy no-swap limits', async () => {
    vi.mocked(api).mockResolvedValue({ ...status, requiresDefaultRestore: true })
    render(<MemorySwapControl />)
    fireEvent.click(await screen.findByRole('button', { name: 'Memory Swap: Off' }))
    expect(screen.getByRole('button', { name: 'Restore Docker default swap' })).toBeEnabled()
    expect(screen.getByText(/Existing maps retain their previous swap limits/)).toBeInTheDocument()
    expect(api).toHaveBeenCalledTimes(1)
  })
})
