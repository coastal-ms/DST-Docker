import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import { PortalAuthGate } from '../../src/auth/PortalAuthGate'

vi.mock('../../src/pages/PlayerPortal', () => ({ default: () => <div>Linked character portal</div> }))

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
  sessionStorage.clear()
})

describe('PortalAuthGate', () => {
  it('shows first-owner guidance on a bare Docker IP without exposing setup or admin content', async () => {
    vi.stubEnv('VITE_DST_EDITION', 'docker')
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => jsonResponse({ accountLoginEnabled: false, authenticated: false, ownerSetupRequired: true, bootstrapAuthorized: false }))
    render(<PortalAuthGate><div>Private dashboard</div></PortalAuthGate>)
    expect(await screen.findByRole('heading', { name: 'First owner setup required' })).toBeInTheDocument()
    expect(screen.queryByText('Private dashboard')).not.toBeInTheDocument()
    expect(screen.queryByText(/Could not load your DST setup/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Create owner account' })).not.toBeInTheDocument()
  })

  it('lets an authorized Docker host choose an owner password and checks confirmation before posting', async () => {
    vi.stubEnv('VITE_DST_EDITION', 'docker')
    const mock = vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => jsonResponse({ accountLoginEnabled: false, authenticated: false, ownerSetupRequired: true, bootstrapAuthorized: true }))
      .mockImplementationOnce(() => jsonResponse({ accountLoginEnabled: true, authenticated: true, ownerSetupRequired: false, account: { role: 'owner', username: 'FixtureOwner' } }))
      .mockImplementationOnce(() => jsonResponse({ ok: true, data: { phase: 'new', assets: { state: 'downloaded', images: [] }, database: null, credentialsSaved: false, profile: null, partitionsPrepared: false, connectionServices: [], services: [], plan: null, desiredState: 'stopped', operation: null } }))
    const user = userEvent.setup()
    render(<PortalAuthGate><div>Private dashboard</div></PortalAuthGate>)
    await screen.findByRole('heading', { name: 'Create your DST owner account' })
    await user.type(screen.getByLabelText('Owner username'), 'FixtureOwner')
    await user.type(screen.getByLabelText('Password', { exact: true }), 'synthetic-password')
    await user.type(screen.getByLabelText('Confirm password'), 'different-password')
    await user.click(screen.getByRole('button', { name: 'Create owner account' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Passwords do not match')
    expect(mock).toHaveBeenCalledTimes(1)
    await user.clear(screen.getByLabelText('Confirm password'))
    await user.type(screen.getByLabelText('Confirm password'), 'synthetic-password')
    await user.click(screen.getByRole('button', { name: 'Create owner account' }))
    expect(await screen.findByRole('button', { name: 'Next', exact: true })).toBeInTheDocument()
    expect(screen.queryByText('Private dashboard')).not.toBeInTheDocument()
    expect(mock.mock.calls[1][0]).toBe('/api/docker/owner/setup')
    expect(JSON.parse((mock.mock.calls[1][1] as RequestInit).body as string)).toEqual({ username: 'FixtureOwner', password: 'synthetic-password' })
  })
  it.each(['windows', 'docker'])('routes an authenticated Player to their portal instead of requested admin content (%s)', async edition => {
    vi.stubEnv('VITE_DST_EDITION', edition)
    vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() => jsonResponse({
      accountLoginEnabled: true, authenticated: true, mustChangePassword: false,
      account: { id: 'p', username: 'player', role: 'player', enabled: true },
    }))
    render(<PortalAuthGate><div>Server administration</div></PortalAuthGate>)
    expect(await screen.findByText('Linked character portal')).toBeInTheDocument()
    expect(screen.queryByText('Server administration')).not.toBeInTheDocument()
  })

  it('shows incumbent-themed login and returns to the requested portal content', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => jsonResponse({
        accountLoginEnabled: true, authenticated: false, mustChangePassword: false, account: null,
      }))
      .mockImplementationOnce(() => jsonResponse({
        accountLoginEnabled: true,
        authenticated: true,
        mustChangePassword: false,
        account: { id: 'a', username: 'hawk', role: 'admin', enabled: true },
      }))
    const user = userEvent.setup()
    render(<PortalAuthGate><div>Existing dashboard</div></PortalAuthGate>)

    expect(await screen.findByRole('heading', { name: 'Dune Server Tool' })).toBeInTheDocument()
    const loginForm = document.querySelector<HTMLFormElement>('#portal-login-form')
    expect(loginForm).toHaveAttribute('name', 'portal-login')
    expect(loginForm).toHaveAttribute('autocomplete', 'on')
    const usernameInput = screen.getByLabelText('Username')
    expect(usernameInput).toHaveAttribute('name', 'username')
    expect(usernameInput).toHaveAttribute('autocomplete', 'username')
    expect(usernameInput).toHaveAttribute('inputmode', 'text')
    expect(usernameInput).toHaveAttribute('autocapitalize', 'none')
    expect(usernameInput).toHaveAttribute('spellcheck', 'false')
    const passwordInput = screen.getByLabelText('Password')
    expect(passwordInput).toHaveAttribute('name', 'password')
    expect(passwordInput).toHaveAttribute('autocomplete', 'current-password')
    const rememberMe = screen.getByRole('checkbox', { name: /Remember me on this device/i })
    expect(rememberMe).not.toBeChecked()
    expect(screen.getByText(/trusted personal device/i)).toBeInTheDocument()
    await user.type(screen.getByLabelText('Username'), 'hawk')
    await user.type(screen.getByLabelText('Password'), 'one time password')
    await user.click(rememberMe)
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Existing dashboard')).toBeInTheDocument()
    expect(fetchMock.mock.calls[1][0]).toBe('/api/portal-auth/login')
    expect(JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string)).toEqual({
      username: 'hawk',
      password: 'one time password',
      rememberMe: true,
    })
  })

  it('forces a password change and surfaces validation errors', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => jsonResponse({
        accountLoginEnabled: true,
        authenticated: true,
        mustChangePassword: true,
        account: { id: 'a', username: 'owner', role: 'owner', enabled: true },
      }))
    const user = userEvent.setup()
    render(<PortalAuthGate><div>Existing dashboard</div></PortalAuthGate>)

    expect(await screen.findByRole('heading', { name: 'Change your password' })).toBeInTheDocument()
    const changeForm = document.querySelector<HTMLFormElement>('#portal-password-change-form')
    expect(changeForm).toHaveAttribute('name', 'portal-password-change')
    const usernameContext = document.querySelector<HTMLInputElement>('#portal-password-change-username')
    expect(usernameContext).toHaveAttribute('name', 'username')
    expect(usernameContext).toHaveAttribute('autocomplete', 'username')
    expect(usernameContext).toHaveValue('owner')
    expect(screen.getByLabelText('One-time password')).toHaveAttribute('name', 'current-password')
    expect(screen.getByLabelText('One-time password')).toHaveAttribute('autocomplete', 'current-password')
    expect(screen.getByLabelText('New password')).toHaveAttribute('name', 'new-password')
    expect(screen.getByLabelText('New password')).toHaveAttribute('autocomplete', 'new-password')
    expect(screen.getByLabelText('Confirm new password')).toHaveAttribute('autocomplete', 'new-password')
    await user.type(screen.getByLabelText('One-time password'), 'temporary password')
    await user.type(screen.getByLabelText('New password'), 'long new password')
    await user.type(screen.getByLabelText('Confirm new password'), 'different password')
    await user.click(screen.getByRole('button', { name: 'Change password' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('do not match')
  })

  it('keeps legacy portal content unchanged while account mode is disabled', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() => jsonResponse({
      accountLoginEnabled: false, authenticated: false, mustChangePassword: false, account: null,
    }))
    render(<PortalAuthGate><div>Existing dashboard</div></PortalAuthGate>)
    await waitFor(() => expect(screen.getByText('Existing dashboard')).toBeInTheDocument())
    expect(screen.queryByLabelText('Username')).not.toBeInTheDocument()
  })

  it('gives actionable recovery if a forced-change origin check is rejected', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => jsonResponse({
        accountLoginEnabled: true,
        authenticated: true,
        mustChangePassword: true,
        account: { id: 'a', username: 'owner', role: 'owner', enabled: true },
      }))
      .mockImplementationOnce(() => jsonResponse({ error: 'Request origin rejected.' }, 403))
    const user = userEvent.setup()
    render(<PortalAuthGate><div>Existing dashboard</div></PortalAuthGate>)
    await user.type(await screen.findByLabelText('One-time password'), 'temporary password')
    await user.type(screen.getByLabelText('New password'), 'long new password')
    await user.type(screen.getByLabelText('Confirm new password'), 'long new password')
    await user.click(screen.getByRole('button', { name: 'Change password' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Reopen the current Browser Portal QR or stable link/i)
  })
})
