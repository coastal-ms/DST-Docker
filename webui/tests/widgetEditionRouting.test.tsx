import React from 'react'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import App from '../src/App'
import { BrowserRouter } from '../src/router'

vi.mock('../src/hooks/useInstallationMode', () => ({
  InstallationProvider: ({ children }: { children: React.ReactNode }) => children,
  useSoloInstallation: () => false,
  isSoloDestination: () => false,
}))
vi.mock('../src/auth/portalAccess', () => ({ usePortalAccess: () => ({ canAccessOwnerSurfaces: true, canAccessSetup: true }) }))
vi.mock('../src/api/client', () => ({ api: vi.fn().mockResolvedValue({}) }))
vi.mock('../src/pages/WidgetMode', () => ({ default: () => <div>Widget content</div> }))
vi.mock('../src/layout/AppShell', () => ({ AppShell: ({ children }: { children: React.ReactNode }) => children }))
vi.mock('../src/hooks/useStatus', () => ({ StatusProvider: ({ children }: { children: React.ReactNode }) => children }))
vi.mock('../src/components/ReconnectOverlay', () => ({ ReconnectOverlay: () => null }))
vi.mock('../src/components/SettingsApplyProgress', () => ({ SettingsApplyProgress: () => null }))
vi.mock('../src/platform/workspaces', () => ({ WORKSPACE_MANIFEST: [] }))
vi.mock('../src/platform/routes', () => ({ COMPATIBILITY_REDIRECTS: [], LEGACY_ROUTE_MANIFEST: [] }))
vi.mock('../src/pages/PageStub', () => ({ PageStub: () => <div>Normal portal</div> }))

afterEach(() => { cleanup(); vi.unstubAllEnvs(); window.history.replaceState(null, '', '/') })

it('redirects a direct Docker widget URL without mounting Widget mode', async () => {
  vi.stubEnv('VITE_DST_EDITION', 'docker')
  window.history.replaceState(null, '', '/widget')
  render(<BrowserRouter><App /></BrowserRouter>)
  await waitFor(() => expect(window.location.pathname).toBe('/'))
  expect(screen.queryByText('Widget content')).not.toBeInTheDocument()
  expect(screen.getByText('Normal portal')).toBeInTheDocument()
})

it('retains the local Windows Widget mode route', () => {
  vi.stubEnv('VITE_DST_EDITION', 'windows')
  window.history.replaceState(null, '', '/widget')
  render(<BrowserRouter><App /></BrowserRouter>)
  expect(screen.getByText('Widget content')).toBeInTheDocument()
  expect(window.location.pathname).toBe('/widget')
})
