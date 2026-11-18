import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { api } from '../src/api/client'
import { confirmAction } from '../src/util/actionConfirmation'
import { DockerProductUpdateCard } from '../src/pages/docker/DockerProductUpdateCard'
import { version as portalVersion } from '../package.json'
vi.mock('../src/api/client', () => ({ api: vi.fn() }))
vi.mock('../src/util/actionConfirmation', () => ({ confirmAction: vi.fn(() => true) }))
const latest = { supported: true, currentVersion: '1.0.12', latestVersion: '1.0.13', available: true, tag: 'v1.0.13', commit: 'a'.repeat(40) }
afterEach(() => { cleanup(); vi.resetAllMocks() })
describe('DST Docker product updater', () => {
  it('compares versions and installs the exact reviewed release after confirmation', async () => {
    vi.mocked(confirmAction).mockReturnValue(true)
    vi.mocked(api).mockResolvedValueOnce(latest).mockResolvedValueOnce({ operation: { id:'job',phase:'running',message:'Building DST' } })
    render(<DockerProductUpdateCard />)
    await screen.findByText('Version 1.0.13 is available.')
    fireEvent.click(screen.getByRole('button',{name:'Update DST Docker'}))
    await screen.findByText('Building DST')
    expect(api).toHaveBeenLastCalledWith('/api/docker/product-update', { method:'POST',body:JSON.stringify({tag:latest.tag,commit:latest.commit,confirmation:'UPDATE DST DOCKER'}) })
    expect(screen.getByRole('button',{name:'Updating DST Docker…'})).toBeDisabled()
  })
  it('forces a fresh version check', async () => {
    vi.mocked(api).mockResolvedValue(latest)
    render(<DockerProductUpdateCard />)
    await screen.findByText('Version 1.0.13 is available.')
    fireEvent.click(screen.getByRole('button',{name:'Check now'}))
    await waitFor(() => expect(api).toHaveBeenLastCalledWith('/api/docker/product-update?force=1'))
  })
  it('requires the host update service and a newer release', async () => {
    vi.mocked(api).mockResolvedValue({ ...latest, supported:false, available:false, error:'Rerun the installer once' })
    render(<DockerProductUpdateCard />)
    await screen.findByRole('alert')
    expect(screen.getByRole('button',{name:'Update DST Docker'})).toBeDisabled()
  })
  it('does not post when confirmation is declined', async () => {
    vi.mocked(confirmAction).mockReturnValue(false)
    vi.mocked(api).mockResolvedValue(latest)
    render(<DockerProductUpdateCard />)
    await screen.findByText('Version 1.0.13 is available.')
    fireEvent.click(screen.getByRole('button',{name:'Update DST Docker'}))
    expect(api).toHaveBeenCalledTimes(1)
  })
  it('shows a refused update without reporting success', async () => {
    vi.mocked(confirmAction).mockReturnValue(true)
    vi.mocked(api).mockResolvedValueOnce(latest).mockRejectedValueOnce(new Error('Wait for backups to finish before updating DST Docker.'))
    render(<DockerProductUpdateCard />)
    await screen.findByText('Version 1.0.13 is available.')
    fireEvent.click(screen.getByRole('button',{name:'Update DST Docker'}))
    await screen.findByText('Wait for backups to finish before updating DST Docker.')
    expect(screen.queryByText(/installed\. Reload/)).toBeNull()
  })
  it('confirms completion only after the running version matches', async () => {
    vi.mocked(api).mockResolvedValue({ ...latest, currentVersion:'1.0.13', available:false,
      operation:{phase:'completed',toVersion:'1.0.13',id:'job',message:'Finished'} })
    render(<DockerProductUpdateCard />)
    await screen.findByText('DST Docker 1.0.13 is installed. Reload the portal to use the updated interface.')
    expect(screen.getByRole('button',{name:'Reload portal'})).toBeInTheDocument()
    expect(screen.getByRole('button',{name:'Update DST Docker'})).toBeDisabled()
  })
  it('ignores completed update history for a different installed version', async () => {
    vi.mocked(api).mockResolvedValue({ ...latest, currentVersion: portalVersion, available: false,
      operation: { phase: 'completed', toVersion: '1.0.13', id: 'old-update', message: 'Finished' } })
    render(<DockerProductUpdateCard />)
    await screen.findByText('You have this or a newer version.')
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Reload portal' })).toBeNull()
  })
  it('clears the completed update prompt when the loaded portal already matches the installed version', async () => {
    vi.mocked(api).mockResolvedValue({ ...latest, currentVersion:portalVersion, latestVersion:portalVersion, available:false,
      operation:{phase:'completed',toVersion:portalVersion,id:'job',message:'Finished'} })
    render(<DockerProductUpdateCard />)
    await screen.findByText('You have this or a newer version.')
    expect(screen.queryByRole('button',{name:'Reload portal'})).toBeNull()
    expect(screen.queryByText(/Reload the portal to use/)).toBeNull()
    expect(screen.queryByRole('status')).toBeNull()
  })
})
