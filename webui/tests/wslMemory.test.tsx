import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { api } from '../src/api/client'
import { WslMemoryCard } from '../src/pages/docker/WslMemoryCard'
vi.mock('../src/api/client', () => ({ api: vi.fn() }))
const settings={platform:'wsl',available:true,configuredGiB:null,useDefault:true,currentMemoryGiB:39.1,defaultMemoryGiB:40,maxMemoryGiB:80,restartRequired:false}
afterEach(() => { cleanup(); vi.resetAllMocks(); localStorage.clear() })
it('saves a lower limit without a shutdown request and reports restart pending beside Save', async () => {
  vi.mocked(api).mockResolvedValueOnce(settings).mockResolvedValueOnce({...settings,useDefault:false,configuredGiB:24,configuredValue:'24GB',restartRequired:true})
  render(<WslMemoryCard />)
  fireEvent.click(await screen.findByLabelText(/Use WSL default/))
  fireEvent.change(screen.getByLabelText('RAM limit (GiB)'),{target:{value:'24'}})
  fireEvent.click(screen.getByRole('button',{name:'Save WSL RAM limit'}))
  expect(await screen.findByRole('status')).toHaveTextContent('Saved. The new limit applies after a WSL restart.')
  expect(api).toHaveBeenLastCalledWith('/api/docker/host',expect.objectContaining({method:'POST',body:JSON.stringify({action:'memory.set',memoryGiB:24})}))
  expect(api).toHaveBeenCalledTimes(2)
})
it('can restore the WSL default and preserves the selected value on failure', async () => {
  vi.mocked(api).mockResolvedValueOnce({...settings,useDefault:false,configuredGiB:24}).mockRejectedValueOnce(new Error('Configuration changed. Refresh and save again.'))
  render(<WslMemoryCard />)
  await screen.findByLabelText('RAM limit (GiB)')
  fireEvent.click(screen.getByLabelText(/Use WSL default/))
  fireEvent.click(screen.getByRole('button',{name:'Save WSL RAM limit'}))
  expect(await screen.findByRole('alert')).toHaveTextContent('Configuration changed')
  expect(screen.getByLabelText(/Use WSL default/)).toBeChecked()
  expect(api).toHaveBeenLastCalledWith('/api/docker/host',expect.objectContaining({body:JSON.stringify({action:'memory.set',memoryGiB:null})}))
})
it('does not show WSL controls on native Linux', async () => {
  vi.mocked(api).mockResolvedValue({platform:'linux',available:false})
  render(<WslMemoryCard />)
  await waitFor(() => expect(api).toHaveBeenCalled())
  expect(screen.queryByText('WSL RAM limit')).toBeNull()
})
