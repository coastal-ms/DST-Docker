import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LandclaimTimerCard } from '../../src/pages/gameconfig/LandclaimTimerCard'
import { getLandclaimTimer, saveLandclaimTimer } from '../../src/api/gameconfig'
import type { LandclaimTimerState } from '../../src/api/types'
import { chooseBrowserClientFiles } from '../../src/api/browserClientFiles'
vi.mock('../../src/api/gameconfig', () => ({ getLandclaimTimer: vi.fn(), saveLandclaimTimer: vi.fn() }))
vi.mock('../../src/api/browserClientFiles', () => ({ chooseBrowserClientFiles: vi.fn(), isBrowserClientSelectionCancelled: () => false }))
const state: LandclaimTimerState = {
  server: { available: true, enabled: true, seconds: '1', formattedOk: true },
  client: { exists: true, dirExists: true, path: 'fixture/Game.ini', dir: 'fixture', enabled: false, seconds: '', formattedOk: false },
  clientBlock: '',
}
beforeEach(() => vi.stubEnv('VITE_DST_EDITION', ''))
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllEnvs(); localStorage.clear() })
describe('Land claim timer client retry', () => {
  it('keeps Docker saves server-only until the user selects the player destination', async () => {
    vi.stubEnv('VITE_DST_EDITION', 'docker')
    vi.mocked(getLandclaimTimer).mockResolvedValue(state)
    vi.mocked(saveLandclaimTimer).mockResolvedValue({ ...state, ok: true, enabled: true, seconds: '2',
      result: { ok: true, server: { ok: true, applied: true }, client: { ok: true, applied: false } } })
    render(<LandclaimTimerCard vmRunning />)
    const input = await screen.findByRole('spinbutton')
    fireEvent.change(input, { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Review timer changes', exact: true }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent('only; no player file will be changed')
    fireEvent.click(screen.getByRole('button', { name: 'Save server file', exact: true }))
    await waitFor(() => expect(saveLandclaimTimer).toHaveBeenCalledWith(true, '2', false))
    expect(screen.queryByText(/Client Game.ini was not updated/)).not.toBeInTheDocument()
  })

  it('preserves the drafted timer when choosing player files and names a download honestly', async () => {
    vi.stubEnv('VITE_DST_EDITION', 'docker')
    const selected = { ...state, client: { ...state.client, browserDelivery: 'download' as const } }
    vi.mocked(getLandclaimTimer).mockResolvedValue(selected)
    vi.mocked(chooseBrowserClientFiles).mockResolvedValue({} as never)
    vi.mocked(saveLandclaimTimer).mockResolvedValue({ ...selected, ok: true, enabled: true, seconds: '2',
      result: { ok: true, server: { ok: true, applied: true }, client: { ok: true, applied: false, delivery: 'download' } } })
    render(<LandclaimTimerCard vmRunning />)
    const input = await screen.findByRole('spinbutton')
    fireEvent.change(input, { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Choose player config', exact: true }))
    await waitFor(() => expect(screen.getByLabelText(/Also prepare this PC’s player Game.ini download/)).toBeChecked())
    expect(input).toHaveValue(2)
    fireEvent.click(screen.getByRole('button', { name: 'Review timer changes', exact: true }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent('download is not installed automatically')
    fireEvent.click(screen.getByRole('button', { name: 'Save server & Download player file', exact: true }))
    await waitFor(() => expect(saveLandclaimTimer).toHaveBeenCalledWith(true, '2', true))
    expect(await screen.findByRole('status')).toHaveTextContent('No player file was installed')
  })
  it('names both targets and cancels without writing either file', async () => {
    vi.mocked(getLandclaimTimer).mockResolvedValue(state)
    render(<LandclaimTimerCard vmRunning />)
    const review = await screen.findByRole('button', { name: 'Review timer changes' })
    await waitFor(() => expect(review).toBeEnabled())
    fireEvent.click(review)
    expect(screen.getByRole('alertdialog')).toHaveTextContent('server UserGame.ini and the DST host PC’s player Game.ini')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(saveLandclaimTimer).not.toHaveBeenCalled()
    expect(screen.getByRole('spinbutton')).toHaveValue(1)
  })
  it('retries a skipped client write while the server already matches, and reports the skip', async () => {
    vi.mocked(getLandclaimTimer).mockResolvedValue(state)
    vi.mocked(saveLandclaimTimer).mockResolvedValue({ ...state, ok: true, enabled: true, seconds: '1',
      result: { ok: true, server: { ok: true, applied: true }, client: { ok: false, applied: false, reason: 'Game is running.' } } })
    render(<LandclaimTimerCard vmRunning />)
    const apply = await screen.findByRole('button', { name: 'Review timer changes', exact: true })
    await waitFor(() => expect(apply).toBeEnabled())
    fireEvent.click(apply)
    fireEvent.click(screen.getByRole('button', { name: 'Save server & host PC' }))
    expect(await screen.findByText(/Client Game.ini was not updated: Game is running/)).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveClass('text-warning')
    expect(apply).toBeEnabled()
    expect(saveLandclaimTimer).toHaveBeenCalledWith(true, '1')
    vi.mocked(saveLandclaimTimer).mockResolvedValue({ ...state, ok: true, enabled: true, seconds: '1',
      client: { ...state.client, enabled: true, seconds: '1', formattedOk: true },
      result: { ok: true, server: { ok: true, applied: true }, client: { ok: true, applied: true } } })
    fireEvent.click(apply)
    fireEvent.click(screen.getByRole('button', { name: 'Save server & host PC' }))
    await waitFor(() => expect(apply).toBeDisabled())
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.getByText(/client Game.ini updated/)).toBeInTheDocument()
    expect(saveLandclaimTimer).toHaveBeenCalledTimes(2)
  })
  it('can retry clearing a client override after the server is already back to defaults', async () => {
    vi.mocked(getLandclaimTimer).mockResolvedValue({ ...state,
      server: { ...state.server, enabled: false, seconds: '', formattedOk: false },
      client: { ...state.client, enabled: true, seconds: '1', formattedOk: true } })
    vi.mocked(saveLandclaimTimer).mockResolvedValue({ ...state, ok: true, enabled: false, seconds: '',
      server: { ...state.server, enabled: false, seconds: '', formattedOk: false },
      client: { ...state.client, enabled: false, seconds: '', formattedOk: false },
      result: { ok: true, server: { ok: true, applied: true }, client: { ok: true, applied: true } } })
    render(<LandclaimTimerCard vmRunning />)
    const clear = await screen.findByRole('button', { name: 'Review restore defaults' })
    await waitFor(() => expect(clear).toBeEnabled())
    fireEvent.click(clear)
    fireEvent.click(screen.getByRole('button', { name: 'Save server & host PC' }))
    await waitFor(() => expect(clear).toBeDisabled())
    expect(saveLandclaimTimer).toHaveBeenCalledWith(false, '')
  })
  it('does not offer a client-only retry when the client folder is unavailable', async () => {
    vi.mocked(getLandclaimTimer).mockResolvedValue({ ...state, client: { ...state.client, exists: false, dirExists: false } })
    render(<LandclaimTimerCard vmRunning />)
    const apply = await screen.findByRole('button', { name: 'Review timer changes', exact: true })
    await screen.findByRole('spinbutton')
    expect(apply).toBeDisabled()
    expect(saveLandclaimTimer).not.toHaveBeenCalled()
  })
  it('offers re-apply when matching timer values have incomplete client formatting', async () => {
    vi.mocked(getLandclaimTimer).mockResolvedValue({ ...state, client: { ...state.client, enabled: true, seconds: '1', formattedOk: false } })
    render(<LandclaimTimerCard vmRunning />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Review timer changes', exact: true })).toBeEnabled())
  })
  it.each(['server', 'client'] as const)('allows clearing residual lines in the disabled %s but keeps clean defaults idle', async target => {
    const disabled = { ...state,
      server: { ...state.server, enabled: false, seconds: '', formattedOk: false, hasOverrides: false },
      client: { ...state.client, enabled: false, seconds: '', formattedOk: false, hasOverrides: false } }
    const partial = { ...disabled, [target]: { ...disabled[target], hasOverrides: true } }
    vi.mocked(getLandclaimTimer).mockResolvedValue(partial)
    vi.mocked(saveLandclaimTimer).mockResolvedValue({ ...disabled, ok: true, enabled: false, seconds: '',
      result: { ok: true, server: { ok: true, applied: true }, client: { ok: true, applied: true } } })
    render(<LandclaimTimerCard vmRunning />)
    const clear = await screen.findByRole('button', { name: 'Review restore defaults' })
    await waitFor(() => expect(clear).toBeEnabled())
    fireEvent.click(clear)
    fireEvent.click(screen.getByRole('button', { name: 'Save server & host PC' }))
    await waitFor(() => expect(clear).toBeDisabled())
    expect(saveLandclaimTimer).toHaveBeenCalledWith(false, '')
  })
  it('starts with an empty input when enabling and requires a typed value', async () => {
    vi.mocked(getLandclaimTimer).mockResolvedValue({ ...state, server: { ...state.server, enabled: false, seconds: '' } })
    render(<LandclaimTimerCard vmRunning />)
    await screen.findAllByText('game default')
    fireEvent.click(screen.getByRole('checkbox'))
    expect(screen.getByRole('spinbutton')).toHaveValue(null)
    expect(screen.getByRole('spinbutton')).not.toHaveAttribute('placeholder')
    expect(screen.getByRole('button', { name: 'Review timer changes', exact: true })).toBeDisabled()
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '1' } })
    expect(screen.getByRole('button', { name: 'Review timer changes', exact: true })).toBeEnabled()
  })
})
