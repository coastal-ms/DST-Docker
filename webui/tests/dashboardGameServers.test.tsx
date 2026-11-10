import React from 'react'
import { cleanup, render, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { GameServerList } from '../src/pages/Dashboard'

afterEach(() => cleanup())

describe('Game Servers responsive layout', () => {
  it('keeps Overmap first on desktop and mobile across status refreshes without changing the source order', () => {
    const source = ['Survival_1', 'DeepDesert_1', 'Overmap', 'SH_Arrakeen'].map(map => ({ map, phase: 'Starting', ready: 'Unknown', players: 'Unknown', age: '1m' }))
    const { container, rerender } = render(<GameServerList servers={source} />)
    const desktopNames = () => Array.from(container.querySelectorAll('tbody tr td:first-child')).map(cell => cell.textContent?.trim())
    const mobileNames = () => Array.from(container.querySelectorAll('[data-game-server-layout="stacked"] li p:first-child')).map(cell => cell.textContent?.trim())
    const expected = ['Overmap', 'Hagga Basin', 'Deep Desert', 'Arrakeen']
    expect(desktopNames()).toEqual(expected)
    expect(mobileNames()).toEqual(expected)
    expect(source.map(server => server.map)).toEqual(['Survival_1', 'DeepDesert_1', 'Overmap', 'SH_Arrakeen'])
    rerender(<GameServerList servers={[source[1], source[0], {...source[2], phase: 'Running', ready: 'True'}, source[3]]} />)
    expect(desktopNames()).toEqual(['Overmap', 'Deep Desert', 'Hagga Basin', 'Arrakeen'])
    expect(mobileNames()).toEqual(desktopNames())
  })
  const servers = [{
    map: 'Survival_1',
    sietchName: 'Long Sietch Name That Must Wrap',
    phase: 'Startup',
    ready: 'false',
    players: '3',
    age: '6h23m',
  }]

  it('keeps every pod field in a compact stacked mobile row without horizontal scrolling', () => {
    const { container } = render(<GameServerList servers={servers} />)
    const stacked = container.querySelector('[data-game-server-layout="stacked"]')

    expect(stacked).toHaveClass('md:hidden')
    expect(stacked).not.toHaveClass('overflow-x-auto')
    expect(within(stacked as HTMLElement).getByText('Long Sietch Name That Must Wrap')).toBeInTheDocument()
    expect(within(stacked as HTMLElement).getByText('Hagga Basin')).toBeInTheDocument()
    const phaseLabel = stacked?.querySelector('.sr-only')
    expect(phaseLabel).toHaveTextContent('Phase:')
    expect(phaseLabel?.parentElement).toHaveTextContent('Phase: Startup')
    expect(within(stacked as HTMLElement).getByText('Ready')).toBeInTheDocument()
    expect(within(stacked as HTMLElement).getByText('false')).toBeInTheDocument()
    expect(within(stacked as HTMLElement).getByText('Players')).toBeInTheDocument()
    expect(within(stacked as HTMLElement).getByText('3')).toBeInTheDocument()
    expect(within(stacked as HTMLElement).getByText('Age')).toBeInTheDocument()
    expect(within(stacked as HTMLElement).getByText('6h23m')).toBeInTheDocument()
  })

  it('preserves a fixed-layout desktop table without a minimum-width overflow trap', () => {
    const { container } = render(<GameServerList servers={servers} />)
    const desktop = container.querySelector('[data-game-server-layout="table"]')
    const table = within(desktop as HTMLElement).getByRole('table')

    expect(desktop).toHaveClass('min-w-0', 'md:block')
    expect(desktop).not.toHaveClass('overflow-x-auto')
    expect(table).toHaveClass('table-fixed', 'w-full')
    expect(table).not.toHaveClass('min-w-[540px]')
    for (const heading of ['Map', 'Phase', 'Ready', 'Players', 'Age']) {
      expect(within(table).getByRole('columnheader', { name: heading })).toBeInTheDocument()
    }
  })
})
