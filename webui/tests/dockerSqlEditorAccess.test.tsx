import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Database } from '../src/pages/Database'
const mocks=vi.hoisted(()=>({ local:false, owner:true }))
vi.mock('../src/util/viewer',()=>({isLocalViewer:()=>mocks.local}))
vi.mock('../src/auth/portalAccess',()=>({usePortalAccess:()=>({canAccessOwnerSurfaces:mocks.owner})}))
vi.mock('../src/hooks/useStatus',()=>({useStatus:()=>({status:{vm:{running:false},bg:{state:'stopped'}},forceRefresh:vi.fn()})}))
vi.mock('../src/api/client',()=>({api:vi.fn(async()=>({ok:true,data:{},schedule:{},history:[]})),withOnlinePlayerGuard:vi.fn()}))
vi.mock('@monaco-editor/react',()=>({default:()=> <div data-testid="sql-editor" />,loader:{config:vi.fn()}}))
vi.mock('../src/pages/database/VmInfoCard',()=>({VmInfoCard:()=>null}))
vi.mock('../src/pages/docker/DockerDatabaseControl',()=>({DockerDatabaseControl:()=>null}))
vi.mock('../src/pages/docker/DockerBackupMirror',()=>({DockerBackupMirror:()=>null}))
beforeEach(()=>{mocks.local=false;mocks.owner=true;vi.stubEnv('VITE_DST_EDITION','docker')})
afterEach(()=>{cleanup();vi.unstubAllEnvs()})
it('shows the SQL editor for a Docker Owner connecting over the network',()=>{
 render(<Database />)
 expect(screen.getByTestId('sql-editor')).toBeInTheDocument()
 expect(screen.getByText('Read-only')).toBeInTheDocument()
})
it('keeps SQL hidden from delegated Docker accounts even on loopback',()=>{
 mocks.owner=false;mocks.local=true
 render(<Database />)
 expect(screen.queryByTestId('sql-editor')).not.toBeInTheDocument()
})
it('retains the Windows remote SQL restriction for an Owner',()=>{
 vi.stubEnv('VITE_DST_EDITION','windows')
 render(<Database />)
 expect(screen.queryByTestId('sql-editor')).not.toBeInTheDocument()
})
it('retains SQL access on the Windows host',()=>{
 vi.stubEnv('VITE_DST_EDITION','windows');mocks.local=true
 render(<Database />)
 expect(screen.getByTestId('sql-editor')).toBeInTheDocument()
})
