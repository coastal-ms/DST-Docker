import React from 'react'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../src/api/client'
import { RemoteMapQr, remoteMapLink } from '../src/pages/workspaces/RemoteMapQr'

const viewer = vi.hoisted(() => ({ local: false, accounts: true }))
vi.mock('../src/util/viewer', () => ({ isLocalViewer: () => viewer.local }))
vi.mock('../src/auth/PortalAuthGate', () => ({ usePortalAuth: () => viewer.accounts ? {status:{accountLoginEnabled:true}} : null }))
vi.mock('../src/api/client', () => ({ api:vi.fn() }))
vi.mock('qrcode.react', () => ({ QRCodeSVG: ({value}:{value:string}) => <svg aria-label="Map QR" data-value={value} /> }))

afterEach(() => { cleanup(); vi.unstubAllEnvs(); vi.clearAllMocks(); viewer.local=false;viewer.accounts=true;delete window.__duneRemoteToken })
describe('remote lifecycle map QR', () => {
  it('opens the live map on the same portal with account login and no transferred credential', () => {
    window.__duneRemoteToken = 'fixture-secret'
    render(<RemoteMapQr />)
    expect(screen.getByLabelText('Map QR')).toHaveAttribute('data-value', `${window.location.origin}/map?view=live`)
    expect(screen.getByText('Sign in on that device.')).toBeInTheDocument()
  })
  it('reuses existing magic-link access without remote settings or pairing requests', () => {
    viewer.accounts=false;window.__duneRemoteToken='fixture-key'
    render(<RemoteMapQr />)
    expect(screen.getByLabelText('Map QR')).toHaveAttribute('data-value', `${window.location.origin}/map?view=live&key=fixture-key`)
    expect(screen.queryByText('Sign in on that device.')).not.toBeInTheDocument()
  })
  it('does not show an unusable loopback QR in the desktop viewer', () => {
    viewer.local=true
    render(<RemoteMapQr />)
    expect(screen.queryByLabelText('Map QR')).not.toBeInTheDocument()
  })
  it('encodes legacy access keys and never adds one in account mode', () => {
    const url=new URL(remoteMapLink('https://portal.example.test',false,'a+b&c'))
    expect(url.searchParams.get('key')).toBe('a+b&c')
    expect(url.searchParams.get('view')).toBe('live')
    expect(remoteMapLink('https://portal.example.test',true,'ignored')).toBe('https://portal.example.test/map?view=live')
  })
})

it('uses the configured Docker address without transferring a session',async()=>{
 vi.stubEnv('VITE_DST_EDITION','docker')
 vi.mocked(api).mockResolvedValue({url:'https://dst.tail123.ts.net',mode:'public'})
 render(<RemoteMapQr />)
 await waitFor(()=>expect(screen.getByLabelText('Map QR')).toHaveAttribute('data-value','https://dst.tail123.ts.net/map?view=live'))
 expect(screen.getByText('Public HTTPS link.')).toBeInTheDocument()
})
