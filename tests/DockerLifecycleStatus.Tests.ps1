BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerManager.ps1'
}
Describe 'Docker database lifecycle presentation' {
    BeforeEach {
        $script:snapshot=Join-Path $TestDrive 'status.json'
        @{available=$true;observedAt=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()}|ConvertTo-Json|Set-Content -LiteralPath $script:snapshot
        $script:metadata=@{profile=@{name='Fixture';address='127.0.0.1'};desiredState='stopped';operation=@{phase='completed'};
          database=@{state='exited';health='unhealthy'};connectionServices=@();services=@();plan=@{games=@()}}
        Mock Invoke-DuneDockerManager { @{ok=$true;data=$script:metadata} }
    }
    It 'shows a stopped database without carrying its previous unhealthy health result into the UI' {
        $status=Get-DuneDockerStatus -SnapshotPath $script:snapshot -LifecycleOnly
        $status.bg.info.database|Should -Be 'Stopped'
        $status.bg.state|Should -Be 'stopped'
    }
    It 'does not report a completed stop while an owned service still runs' {
        $script:metadata.operation.phase='failed'
        $script:metadata.services=@(@{component='director';state='running'})
        (Get-DuneDockerStatus -SnapshotPath $script:snapshot -LifecycleOnly).bg.state | Should -Be 'stopping'
    }
    It 'shows stopping in game phases and BG info even with stale ready heartbeats' {
        $script:metadata.operation=@{phase='running';action='services.stop'}
        $script:metadata.plan.games=@(@{map='Survival_1';partition=1})
        $script:metadata.services=@(@{component='game-1';state='running';gameReady=$true;desiredState='stopped'})
        $status=Get-DuneDockerStatus -SnapshotPath $script:snapshot -LifecycleOnly
        $status.bg.state|Should -Be 'stopping'
        $status.bg.info.status|Should -Be 'stopping'
        $status.bg.gameServers[0].phase|Should -Be 'Stopping'
        $status.bg.gameServers[0].ready|Should -Be 'False'
    }
    It 'retains a real health failure while the database is running' {
        $script:metadata.database.state='running'
        (Get-DuneDockerStatus -SnapshotPath $script:snapshot -LifecycleOnly).bg.info.database|Should -Be 'unhealthy'
        $script:metadata.database.health='healthy'
        (Get-DuneDockerStatus -SnapshotPath $script:snapshot -LifecycleOnly).bg.info.database|Should -Be 'Ready'
    }
    It 'does not call the battlegroup ready when a stopped database has a stale healthy result' {
        $script:metadata.database.health='healthy';$script:metadata.desiredState='running'
        $script:metadata.services=@(@{component='director';state='running'},@{component='gateway';state='running'},@{component='game-1';state='running';gameReady=$true;desiredState='running'})
        $script:metadata.connectionServices=@(@{health='healthy'})
        $status=Get-DuneDockerStatus -SnapshotPath $script:snapshot -LifecycleOnly
        $status.bg.info.database|Should -Be 'Stopped'
        $status.bg.state|Should -Not -Be 'running'
    }
}
