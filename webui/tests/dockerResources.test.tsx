import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import DockerResourcesCard from '../src/pages/docker/DockerResourcesCard'

const request = vi.hoisted(() => vi.fn())
vi.mock('../src/api/client', () => ({ api: request }))
const snapshot = {
  memoryGiB: 24, cpuCount: 8, serviceReserveGiB: 2, reservedMemoryGiB: 0, reservedCpus: 0,
  host: { memoryBytes: 32 * 1024 ** 3, availableBytes: 30 * 1024 ** 3, cpus: 8 },
  worldRunning: false, pending: false,
  maps: [{ map: 'Survival_1', memoryGiB: 12, cpus: null, initialInstances: 1 }],
}
beforeEach(() => { localStorage.clear(); request.mockResolvedValue(structuredClone(snapshot)) })
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('saves per-map RAM with shared CPU and no editable total CPU budget', async () => {
  render(<DockerResourcesCard />)
  await screen.findByLabelText('Survival_1 RAM')
  expect(screen.queryByLabelText('Game CPU budget')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Server RAM budget (GiB)')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Survival_1 CPUs')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Survival_1 RAM'), { target: { value: '14' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save allocations' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/docker/resources', expect.objectContaining({ method: 'PUT' })))
  const options = request.mock.calls.find(call => call[1]?.method === 'PUT')![1]
  expect(JSON.parse(options.body)).toMatchObject({ memoryGiB: 24, maps: [{ map: 'Survival_1', memoryGiB: 14, cpus: null }] })
  expect(JSON.parse(options.body)).not.toHaveProperty('cpuCount')
})

it('lets users opt into a per-map CPU cap and clear it back to shared', async () => {
  render(<DockerResourcesCard />)
  await screen.findByLabelText('Survival_1 RAM')
  fireEvent.click(screen.getByLabelText('Show optional per-map CPU limits'))
  fireEvent.change(screen.getByLabelText('Survival_1 CPUs'), { target: { value: '2' } })
  fireEvent.change(screen.getByLabelText('Survival_1 CPUs'), { target: { value: '' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save allocations' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith('/api/docker/resources', expect.objectContaining({ method: 'PUT' })))
  expect(JSON.parse(request.mock.calls.find(call => call[1]?.method === 'PUT')![1].body).maps[0].cpus).toBeNull()
})

it('requires an explicit battlegroup stop before allocations can be changed', async () => {
  request.mockResolvedValue({ ...snapshot, worldRunning: true })
  render(<DockerResourcesCard />)
  await screen.findByText(/Stop the battlegroup before changing/)
  expect(screen.getByLabelText('Survival_1 RAM')).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Save allocations' })).toBeDisabled()
  expect(request).toHaveBeenCalledTimes(1)
})

it('retains the draft and displays rejected changes without claiming success', async () => {
  request.mockImplementation(async (_path, options) => { if (options) throw new Error('Allocation exceeds the host budget.'); return structuredClone(snapshot) })
  render(<DockerResourcesCard />)
  await screen.findByLabelText('Survival_1 RAM')
  fireEvent.change(screen.getByLabelText('Survival_1 RAM'), { target: { value: '14' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save allocations' }))
  await screen.findByRole('alert')
  expect(screen.getByLabelText('Survival_1 RAM')).toHaveValue(14)
  expect(screen.queryByText(/saved and verified/)).not.toBeInTheDocument()
})
