import {afterEach,expect,it,vi} from 'vitest'
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {api} from '../src/api/client'
import {DockerTailscaleAccess} from '../src/pages/docker/DockerTailscaleAccess'
vi.mock('../src/api/client',()=>({api:vi.fn()}))
afterEach(()=>{cleanup();vi.clearAllMocks();vi.useRealTimers()})
it('connects the selected method directly and shows the Tailscale sign-in link',async()=>{
 vi.mocked(api).mockImplementation(async(_path,options)=>options?.method==='PUT'?{mode:'public',phase:'login-required',loginUrl:'https://login.tailscale.com/a/synthetic',message:'Sign in to Tailscale.'}:{mode:'off',phase:'off'})
 const confirm=vi.spyOn(window,'confirm')
 render(<DockerTailscaleAccess />)
 await waitFor(()=>expect(screen.getByRole('button',{name:'Connect'})).toBeEnabled())
 fireEvent.change(screen.getByLabelText('Access method'),{target:{value:'public'}})
 fireEvent.click(screen.getByRole('button',{name:'Connect'}))
 expect(await screen.findByRole('link',{name:'Sign in to Tailscale'})).toHaveAttribute('href','https://login.tailscale.com/a/synthetic')
 expect(vi.mocked(api).mock.calls.find(([,options])=>options?.method==='PUT')?.[1]?.body).toBe(JSON.stringify({mode:'public'}))
 expect(confirm).not.toHaveBeenCalled();confirm.mockRestore()
})
it('shows a connected private address and switches off without touching a map endpoint',async()=>{
 vi.mocked(api).mockImplementation(async(_path,options)=>options?.method==='PUT'?{mode:'off',phase:'off',message:'Remote access is off.'}:{mode:'private',phase:'connected',url:'https://dst.tail123.ts.net'})
 render(<DockerTailscaleAccess />)
 expect(await screen.findByRole('link',{name:'https://dst.tail123.ts.net'})).toBeInTheDocument()
 expect(screen.getByText(/same Tailscale network/)).toBeInTheDocument()
 fireEvent.click(screen.getByRole('button',{name:'Turn off'}))
 expect(await screen.findByText('Remote access is off.')).toBeInTheDocument()
 expect(vi.mocked(api).mock.calls.every(([path])=>path==='/api/docker/tailscale')).toBe(true)
})

it('keeps an action error beside Connect after a successful status poll',async()=>{
 vi.useFakeTimers()
 vi.mocked(api).mockImplementation(async(_path,options)=>{if(options?.method==='PUT')throw new Error('Connection failed. Retry Connect.');return {mode:'off',phase:'off'}})
 await act(async()=>{render(<DockerTailscaleAccess />)})
 await act(async()=>{fireEvent.click(screen.getByRole('button',{name:'Connect'}))})
 expect(screen.getByRole('alert')).toHaveTextContent('Connection failed. Retry Connect.')
 await act(async()=>{await vi.advanceTimersByTimeAsync(4000)})
 expect(screen.getByRole('alert')).toHaveTextContent('Connection failed. Retry Connect.')
})
