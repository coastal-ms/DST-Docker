import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryBalancingControl } from '../src/components/MemoryBalancingControl'

const request = vi.hoisted(() => vi.fn())
vi.mock('../src/api/client', () => ({ api: request }))
vi.mock('../src/components/MemorySwapControl', () => ({ MemorySwapControl: () => null }))
afterEach(() => { cleanup(); request.mockReset() })

it('shows the saved mode and saves classic DST mode without a restart request', async () => {
  request.mockResolvedValueOnce({ enabled: true }).mockResolvedValueOnce({ enabled: false })
  render(<MemoryBalancingControl />)
  const button = await screen.findByRole('switch', { name: 'Memory balancing', checked: true })
  fireEvent.click(button)
  await screen.findByRole('switch', { name: 'Memory balancing', checked: false })
  expect(screen.getByText(/Classic DST behavior/)).toBeInTheDocument()
  expect(request).toHaveBeenLastCalledWith('/api/docker/memory-balancing', { method: 'PUT', body: JSON.stringify({ enabled: false }) })
  expect(request).toHaveBeenCalledTimes(2)
})

it('keeps the displayed choice when saving fails', async () => {
  request.mockResolvedValueOnce({ enabled: false }).mockRejectedValueOnce(new Error('Server operation in progress'))
  render(<MemoryBalancingControl />)
  await waitFor(() => expect(screen.getByRole('switch')).toHaveTextContent('Off'))
  fireEvent.click(screen.getByRole('switch'))
  await screen.findByRole('alert')
  expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false')
})
