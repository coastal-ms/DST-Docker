import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { api } from '../src/api/client'
import DockerLoopbackSettings from '../src/pages/docker/DockerLoopbackSettings'

vi.mock('../src/api/client', () => ({ api: vi.fn() }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const current = { available: true, platform: 'wsl', target: '192.168.23.219', publicIp: '8.8.4.4' }
it('keeps the VM route on load, selection and cancellation', async () => {
  vi.mocked(api).mockResolvedValue(current)
  render(<DockerLoopbackSettings publicIp="8.8.4.4" dockerIp="192.168.23.106" />)
  await screen.findByText('192.168.23.219')
  expect(screen.getByLabelText('Loopback target')).toHaveValue('existing')
  expect(screen.getByRole('button', { name: 'Apply loopback target' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Loopback target'), { target: { value: 'docker' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply loopback target' }))
  expect(screen.getByRole('alertdialog')).toHaveTextContent('192.168.23.106')
  expect(screen.getByRole('alertdialog')).toHaveTextContent('192.168.23.219')
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(vi.mocked(api).mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true)
})
it('sends the old-target guard only after explicit confirmation', async () => {
  vi.mocked(api).mockImplementation(async (_path, options) => options?.method === 'POST' ? { ...current, operation: { id: 'route-change', phase: 'running' } } : current)
  render(<DockerLoopbackSettings publicIp="8.8.4.4" dockerIp="192.168.23.106" />)
  await screen.findByText('192.168.23.219')
  fireEvent.change(screen.getByLabelText('Loopback target'), { target: { value: 'docker' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply loopback target' }))
  fireEvent.click(screen.getAllByRole('button', { name: 'Apply loopback target' })[1])
  await screen.findByText(/Approve the Windows permission prompt/)
  const call = vi.mocked(api).mock.calls.find(([, options]) => options?.method === 'POST')!
  expect(JSON.parse(call[1]!.body as string)).toEqual({ action: 'loopback.set', publicIp: '8.8.4.4', target: '192.168.23.106', expectedTarget: '192.168.23.219', confirmation: 'CHANGE LOOPBACK TARGET' })
})
it('keeps the card and draft through an unavailable refresh without applying anything', async () => {
  vi.mocked(api).mockResolvedValue(current)
  render(<DockerLoopbackSettings publicIp="8.8.4.4" dockerIp="192.168.23.106" />)
  await screen.findByText('192.168.23.219')
  fireEvent.change(screen.getByLabelText('Loopback target'), { target: { value: 'custom' } })
  fireEvent.change(screen.getByLabelText('Server IPv4 address'), { target: { value: '192.168.23.220' } })
  vi.mocked(api).mockResolvedValueOnce({ available: false, platform: 'linux', message: 'Host check temporarily unavailable.' })
  fireEvent.click(screen.getByRole('button', { name: 'Refresh loopback' }))
  await screen.findByText('Host check temporarily unavailable.')
  expect(screen.getByRole('region', { name: 'Same-PC loopback target' })).toBeInTheDocument()
  expect(screen.getByLabelText('Loopback target')).toHaveValue('custom')
  expect(screen.getByLabelText('Server IPv4 address')).toHaveValue('192.168.23.220')
  expect(screen.getByRole('button', { name: 'Apply loopback target' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Refresh loopback' }))
  await screen.findByRole('button', { name: 'Refresh loopback' })
  expect(screen.getByLabelText('Server IPv4 address')).toHaveValue('192.168.23.220')
  expect(vi.mocked(api).mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true)
})

it('blocks a shared Docker address as either a preset or a custom next hop', async () => {
  vi.mocked(api).mockResolvedValue({ ...current, windowsAddresses: ['192.168.23.106'] })
  render(<DockerLoopbackSettings publicIp="8.8.4.4" dockerIp="192.168.23.106" />)
  await screen.findByText(/Docker shares this PC/)
  expect(screen.getByRole('option', { name: 'Docker (192.168.23.106)' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Loopback target'), { target: { value: 'custom' } })
  fireEvent.change(screen.getByLabelText('Server IPv4 address'), { target: { value: '192.168.23.106' } })
  expect(screen.getByRole('button', { name: 'Apply loopback target' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Loopback target'), { target: { value: 'router' } })
  expect(screen.getByRole('button', { name: 'Apply loopback target' })).toBeEnabled()
})

it('disables the Docker option in mirrored mode with an older host response', async () => {
  vi.mocked(api).mockResolvedValue(current)
  render(<DockerLoopbackSettings publicIp="8.8.4.4" dockerIp="192.168.23.106" sharedLan />)
  expect(await screen.findByRole('option', { name: 'Docker (192.168.23.106)' })).toBeDisabled()
})
