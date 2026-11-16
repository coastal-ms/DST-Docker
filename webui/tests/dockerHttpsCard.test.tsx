import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DockerHttpsCard } from '../src/pages/docker/DockerHttpsCard'
import { api } from '../src/api/client'
vi.mock('../src/api/client',()=>({api:vi.fn(),authenticatedApiNavigation:(path:string)=>path}))
vi.mock('../src/util/actionConfirmation',()=>({confirmAction:vi.fn(()=>true)}))
const initial={supported:true,enabled:false,prepared:false,url:'',address:'',port:8088,addresses:['192.0.2.1'],certificateAvailable:false}
const prepared={...initial,prepared:true,url:'https://192.0.2.1:8088',address:'192.0.2.1',certificateAvailable:true,sha256:'a'.repeat(64)}
beforeEach(()=>{vi.mocked(api).mockResolvedValue(initial)})
afterEach(()=>{cleanup();vi.clearAllMocks();vi.useRealTimers()})
it('prepares HTTPS on the selected host address without enabling it',async()=>{
 render(<DockerHttpsCard />)
 const button=await screen.findByRole('button',{name:'Prepare HTTPS'})
 await waitFor(()=>expect(button).toBeEnabled());fireEvent.click(button)
 await waitFor(()=>expect(api).toHaveBeenLastCalledWith('/api/docker/https',{method:'POST',body:JSON.stringify({action:'prepare',address:'192.0.2.1'})}))
 expect(screen.queryByRole('button',{name:'Enable HTTPS'})).not.toBeInTheDocument()
})
it('offers public certificate download before the explicit trust-and-enable step',async()=>{
 vi.mocked(api).mockResolvedValue(prepared)
 render(<DockerHttpsCard />)
 expect(await screen.findByRole('link',{name:'Download certificate'})).toHaveAttribute('href','/api/docker/https/certificate')
 const enable=screen.getByRole('button',{name:'Enable HTTPS'})
 expect(enable).toBeDisabled()
 fireEvent.click(screen.getByRole('checkbox',{name:'I have trusted this certificate on this device.'}))
 expect(enable).toBeEnabled();fireEvent.click(enable)
 await waitFor(()=>expect(api).toHaveBeenLastCalledWith('/api/docker/https',{method:'POST',body:JSON.stringify({action:'enable',sha256:prepared.sha256})}))
 expect(screen.getByRole('link',{name:'Open HTTPS portal'})).toHaveAttribute('href',prepared.url+'/settings')
})
it('resets device trust confirmation when the prepared CA identity changes',async()=>{
 vi.useFakeTimers();vi.mocked(api).mockResolvedValue(prepared)
 render(<DockerHttpsCard />);await act(async()=>{})
 fireEvent.click(screen.getByRole('checkbox'));expect(screen.getByRole('button',{name:'Enable HTTPS'})).toBeEnabled()
 vi.mocked(api).mockResolvedValue({...prepared,sha256:'b'.repeat(64)})
 await act(async()=>{await vi.advanceTimersByTimeAsync(4000)})
 expect(screen.getByRole('checkbox')).not.toBeChecked();expect(screen.getByRole('button',{name:'Enable HTTPS'})).toBeDisabled()
})
it('keeps HTTP recovery available and never labels a downloaded certificate as installed',async()=>{
 vi.mocked(api).mockResolvedValue({...prepared,enabled:true})
 render(<DockerHttpsCard />)
 fireEvent.click(await screen.findByRole('button',{name:'Return to HTTP'}))
 await waitFor(()=>expect(api).toHaveBeenLastCalledWith('/api/docker/https',{method:'POST',body:JSON.stringify({action:'disable'})}))
 expect(screen.getByRole('link',{name:'Open HTTP portal'})).toHaveAttribute('href','http://192.0.2.1:8088/settings')
 expect(screen.getByText(/Downloading alone does not install it/)).toBeInTheDocument()
})
it('shows missing host-service guidance rather than nonworking setup buttons',async()=>{
 vi.mocked(api).mockResolvedValue({supported:false,error:'Rerun the installer in the same folder.'})
 render(<DockerHttpsCard />)
 expect(await screen.findByText('Rerun the installer in the same folder.')).toBeInTheDocument()
 expect(screen.queryByRole('button',{name:'Prepare HTTPS'})).not.toBeInTheDocument()
})
