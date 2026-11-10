import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { DockerClientInstructions } from '../../src/pages/gameconfig/DockerClientInstructions'
import { getLandclaimTimer } from '../../src/api/gameconfig'
vi.mock('../../src/api/gameconfig', () => ({ getLandclaimTimer: vi.fn() }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const entries = [
  { file: 'game' as const, path: 'Game.ini', block: '[Player]\nPlayerInventoryStartingSize=125' },
  { file: 'engine' as const, path: 'Engine.ini', block: '[ConsoleVariables]\nVehicle.MaxVehiclesPerPlayer=6' },
]
it('copies all saved requirements together and refreshes the timer after a specialized save', async () => {
  vi.mocked(getLandclaimTimer).mockResolvedValue({ server: { available: true, enabled: true }, clientBlock: '[Building]\nTimer=2' } as never)
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  render(<DockerClientInstructions entries={entries} ready />)
  const copy = screen.getByRole('button', { name: 'Copy instructions' })
  await waitFor(() => expect(copy).toBeEnabled())
  fireEvent.click(copy)
  await screen.findByText('Instructions copied.')
  expect(writeText.mock.calls[0][0]).toContain('PlayerInventoryStartingSize=125')
  expect(writeText.mock.calls[0][0]).toContain('Vehicle.MaxVehiclesPerPlayer=6')
  expect(writeText.mock.calls[0][0]).toContain('Timer=2')
  expect(writeText.mock.calls[0][0]).toContain('Remove only entries you previously added for DST')
  vi.mocked(getLandclaimTimer).mockResolvedValue({ server: { available: true, enabled: false }, clientBlock: '' } as never)
  fireEvent(window, new Event('dst:player-instructions'))
  await waitFor(() => expect(copy).toBeEnabled())
  fireEvent.click(copy)
  expect(writeText.mock.calls.at(-1)?.[0]).not.toContain('Timer=2')
})
it('prevents sharing an incomplete list when saved timer settings cannot be read', async () => {
  vi.mocked(getLandclaimTimer).mockRejectedValue(new Error('reconnecting'))
  render(<DockerClientInstructions entries={entries} ready />)
  await screen.findByRole('alert')
  expect(screen.getByRole('button', { name: 'Copy instructions' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Download instructions' })).toBeDisabled()
})
