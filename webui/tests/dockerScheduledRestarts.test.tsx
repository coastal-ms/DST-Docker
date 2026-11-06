import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ScheduledRestarts } from '../src/pages/dashboard/ScheduledRestarts'

const request = vi.hoisted(() => ({ get: vi.fn(), save: vi.fn(), check: vi.fn(), discord: vi.fn() }))
vi.mock('../src/api/restartSchedule', () => ({
  getRestartSchedule: request.get, saveRestartSchedule: request.save, checkFuncomUpdate: request.check, testDiscordWebhook: request.discord,
}))
const snapshot = {
  enabled: false, time: '04:00', timeZone: 'America/New_York', hostingBackend: 'docker', broadcastLeadMinutes: 10,
  applyFuncomUpdates: false, discordEnabled: false, discordNotifyOnline: false, discordNotifyOffline: false,
  discordNotifyRestarting: false, discordNotifyUpdate: false, discordWebhookSet: false, discordMentionId: '', lastRestartDate: '',
  lastResult: '', updateAvailable: false, installedBuild: '', latestBuild: '', updateCheckedAt: '',
}
beforeEach(() => {
  localStorage.setItem('dst.schedRestarts.expanded', '1')
  request.get.mockResolvedValue({ ...snapshot })
  request.save.mockImplementation(async body => ({ ...snapshot, ...body }))
})
afterEach(() => { cleanup(); localStorage.clear(); vi.resetAllMocks() })

it('keeps the existing schedule card and saves the explicit Docker time zone', async () => {
  render(<ScheduledRestarts />)
  const zone = await screen.findByLabelText('Restart time zone')
  expect(zone).toHaveValue('America/New_York')
  expect(screen.getByText(/inside the Docker stack while your browser is closed/)).toBeInTheDocument()
  fireEvent.change(zone, { target: { value: 'Europe/London' } })
  fireEvent.click(screen.getByRole('checkbox', { name: 'Enable daily restart' }))
  fireEvent.click(screen.getByRole('button', { name: /Save/ }))
  await waitFor(() => expect(request.save).toHaveBeenCalledWith(expect.objectContaining({ enabled: true, timeZone: 'Europe/London', time: '04:00' })))
  expect(screen.getByRole('checkbox', { name: /Apply available Funcom server updates/ })).toBeDisabled()
  expect(request.check).not.toHaveBeenCalled()
})

it('retains Windows schedule wording and payload without a Docker zone control', async () => {
  request.get.mockResolvedValue({ ...snapshot, hostingBackend: 'hyperv' })
  render(<ScheduledRestarts />)
  await screen.findByText(/Daily restart\/update maintenance runs from the VM cron/)
  expect(screen.queryByLabelText('Restart time zone')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Enable daily restart' }))
  fireEvent.click(screen.getByRole('button', { name: /Save/ }))
  await waitFor(() => expect(request.save).toHaveBeenCalled())
  expect(request.save.mock.calls[0][0]).not.toHaveProperty('timeZone')
})

it('recovers worker health without replacing an unsaved schedule draft', async () => {
  let finish!: (value: unknown) => void
  request.get.mockResolvedValueOnce({ ...snapshot, automationHealthy: false, automationMessage: 'Worker starting' })
    .mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  render(<ScheduledRestarts />)
  const zone = await screen.findByLabelText('Restart time zone')
  fireEvent.change(zone, { target: { value: 'Europe/London' } })
  fireEvent.change(screen.getByLabelText('Daily restart time'), { target: { value: '05:30' } })
  await waitFor(() => expect(request.get).toHaveBeenCalledTimes(2))
  await act(async () => { finish({ ...snapshot, automationHealthy: true, automationMessage: 'Worker ready', lastResult: 'Latest result' }) })
  expect(zone).toHaveValue('Europe/London')
  expect(screen.getByLabelText('Daily restart time')).toHaveValue('05:30')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByText('Latest result')).toBeInTheDocument()
})

it('checks for Docker updates without resetting the unsaved schedule', async () => {
  request.check.mockResolvedValue({ available: true, message: 'Update available', installedBuild: '120', latestBuild: '121', checkedAt: '2026-11-06T10:00:00Z' })
  render(<ScheduledRestarts />)
  const zone = await screen.findByLabelText('Restart time zone')
  fireEvent.change(zone, { target: { value: 'Europe/London' } })
  fireEvent.click(screen.getByRole('button', { name: 'Check for server update' }))
  await screen.findByText('Update available')
  expect(zone).toHaveValue('Europe/London')
  expect(request.get).toHaveBeenCalledTimes(1)
  expect(request.save).not.toHaveBeenCalled()
})
