import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { api } from '../src/api/client'
import { DockerHostControls } from '../src/pages/commands/DockerHostControls'
const state = vi.hoisted(() => ({ role: 'owner' }))
vi.mock('../src/api/client', () => ({ api: vi.fn() }))
vi.mock('../src/auth/PortalAuthGate', () => ({ usePortalAuth: () => ({ status: { account: { role: state.role } } }) }))
afterEach(() => { cleanup(); vi.clearAllMocks(); state.role = 'owner' })
describe('WSL host controls', () => {
  it('keeps shutdown and shortcut controls visible when the WSL host session is disconnected', async () => {
    vi.mocked(api).mockResolvedValue({ available: false, platform: 'wsl', message: 'Start DST using its desktop icon to enable WSL host controls.' } as never)
    render(<DockerHostControls />)
    expect(await screen.findByText('Start DST using its desktop icon to enable WSL host controls.')).toBeInTheDocument()
    expect(screen.getByRole('button',{name:'Shut down host'})).toBeDisabled()
    expect(screen.getByRole('button',{name:'Create desktop shortcut'})).toBeDisabled()
  })
  it('omits WSL controls on a native Linux host', async () => {
    vi.mocked(api).mockResolvedValue({ available: false, platform: 'linux', message: '' } as never)
    render(<DockerHostControls />)
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Windows host controls' })).toBeNull())
  })
  it('shows console recovery as starting rather than shutting down', async () => {
    vi.mocked(api).mockResolvedValue({ available: true, busy: true, phase: 'starting', message: 'Reopening the DST console...' } as never)
    render(<DockerHostControls />)
    expect(await screen.findByRole('button', { name: 'Starting…' })).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('Reopening the DST console')
  })
  it('starts shutdown directly and shows progress before the page disconnects', async () => {
    vi.mocked(api).mockResolvedValue({ available: true, message: 'Ready' } as never)
    render(<DockerHostControls />)
    const button = await screen.findByRole('button', { name: 'Shut down host' })
    await waitFor(() => expect(button).toBeEnabled())
    fireEvent.click(button)
    expect(screen.queryByRole('alertdialog')).toBeNull()
    await screen.findByText(/Shutting down: stopping/)
    expect(api).toHaveBeenCalledWith('/api/docker/host', expect.objectContaining({ method: 'POST', body: JSON.stringify({ action: 'shutdown', confirmation: 'SHUT DOWN HOST' }) }))
    expect(screen.getByRole('button', { name: 'Shutting down…' })).toBeDisabled()
  })
  it('shows a refusal and leaves the host available', async () => {
    vi.mocked(api).mockImplementation(async (_, options) => {
      if (options?.method === 'POST') throw new Error('Another WSL distribution is running.')
      return { available: true, message: 'Ready' } as never
    })
    render(<DockerHostControls />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Shut down host' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Shut down host' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Another WSL distribution')
    expect(screen.getByRole('button', { name: 'Shut down host' })).toBeEnabled()
  })
  it('recreates the icon without shutting down the host', async () => {
    vi.mocked(api).mockResolvedValue({ available: true, message: 'Ready', path: 'Desktop/DST Docker.lnk' } as never)
    render(<DockerHostControls />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create desktop shortcut' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Create desktop shortcut' }))
    await screen.findByText(/Desktop shortcut created/)
    expect(api).toHaveBeenCalledWith('/api/docker/host', expect.objectContaining({ body: JSON.stringify({ action: 'shortcut' }) }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })
  it('does not expose owner host actions to an admin', () => {
    state.role = 'admin';render(<DockerHostControls />)
    expect(screen.queryByRole('button')).toBeNull();expect(api).not.toHaveBeenCalled()
  })
})
