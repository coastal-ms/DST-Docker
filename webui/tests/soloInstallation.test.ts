import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getVisibleNavItems } from '../src/nav'
import { getDeckDestinations } from '../src/layout/commandDeckModel'

const access = { local: true, windows: true, canAccessOwnerSurfaces: true, soloOnly: true }
beforeEach(() => vi.stubEnv('VITE_DST_EDITION', ''))
afterEach(() => vi.unstubAllEnvs())

describe('Solo installation navigation', () => {
  it('keeps Solo out of Docker navigation and the Command Deck even on a local Windows browser', () => {
    vi.stubEnv('VITE_DST_EDITION', 'docker')
    const dockerAccess = { ...access, soloOnly: false }
    expect(getVisibleNavItems(dockerAccess).some(item => item.to === '/solo')).toBe(false)
    expect(getDeckDestinations(dockerAccess).some(item => item.to === '/solo')).toBe(false)
    expect(getVisibleNavItems(dockerAccess).some(item => item.to === '/server-settings')).toBe(true)
  })
  it('offers Solo and shared settings without dedicated-server controls', () => {
    const paths = getVisibleNavItems(access).map(item => item.to)
    expect(paths).toContain('/solo')
    expect(paths).toContain('/settings')
    expect(paths).not.toContain('/server-settings')
    expect(paths).not.toContain('/operations')
    expect(paths).not.toContain('/gameconfig')
  })
  it('does not reintroduce server workspaces through the Command Deck finder', () => {
    expect(getDeckDestinations(access).every(item => ['/solo', '/settings', '/sponsors'].includes(item.to))).toBe(true)
  })
  it('keeps server navigation for existing full installations', () => {
    expect(getVisibleNavItems({ ...access, soloOnly: false }).some(item => item.to === '/server-settings')).toBe(true)
  })
})
