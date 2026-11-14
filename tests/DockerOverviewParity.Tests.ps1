BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerManager.ps1'
    Import-DstLib 'RestartSchedule.ps1'
    function global:Invoke-DuneSqlQuery {param($Ip,$ReadOnly,$Sql)}
    function global:ConvertTo-DuneRowMaps {param($Result);$Result.rows}
    function global:Invoke-WithDuneLock {param($Name,$TimeoutSec,$Script); & $Script}
}
Describe 'Docker Overview current observations' {
    It 'distinguishes known loading and unloading without guessing from readiness' {
        $service=@{component='game-4';state='running';desiredState='running';gameReady=$false}
        Get-DuneDockerGamePhase $service @{phase='completed'} | Should -Be 'Configuring'
        Get-DuneDockerGamePhase $service @{phase='running';action='maps.start';partition=4} | Should -Be 'Loading'
        Get-DuneDockerGamePhase $service @{phase='running';action='maps.stop';partition=4} | Should -Be 'Unloading'
        $service.desiredState='stopped'
        Get-DuneDockerGamePhase $service @{phase='completed'} | Should -Be 'Unloading'
        $service.desiredState='running';$service.gameReady=$true
        Get-DuneDockerGamePhase $service @{phase='completed'} | Should -Be 'Running'
    }
    BeforeEach {
        $script:state=Get-DuneRestartScheduleDefault
        $script:state.latestBuild='121';$script:state.installedBuild='120';$script:state.updateAvailable=$true
        Mock Get-DuneRestartSchedule {$script:state}
        Mock Save-DuneRestartSchedule {}
    }
    It 'clears the stale update flag after observing the installed build without a network lookup' {
        Sync-DuneFuncomInstalledBuild -InstalledBuild '121' | Should -BeTrue
        $script:state.updateAvailable | Should -BeFalse
        $script:state.installedBuild | Should -Be '121'
        Should -Invoke Save-DuneRestartSchedule -Times 1
        Sync-DuneFuncomInstalledBuild -InstalledBuild '121' | Should -BeFalse
    }
    It 'preserves a genuine update and ignores an invalid installed observation' {
        Sync-DuneFuncomInstalledBuild -InstalledBuild '119' | Should -BeTrue
        $script:state.updateAvailable | Should -BeTrue
        Sync-DuneFuncomInstalledBuild -InstalledBuild '' | Should -BeFalse
        $script:state.installedBuild | Should -Be '119'
    }
    It 'counts online characters only against the current running server identities' {
        $id='A'*22;$other='B'*22
        Mock Invoke-DuneSqlQuery {param($Ip,$ReadOnly,$Sql);@{ok=$true;rows=@(@{server_id=('A'*22);players='2'},@{server_id=('B'*22);players='9'})}}
        $metadata=@{database=@{health='healthy';state='running'};services=@(@{component='game-8';state='running';gameServerId=$id},@{component='game-1';state='exited';gameServerId=$other})}
        $counts=Get-DuneDockerPlayerCounts -Metadata $metadata
        $counts[$id] | Should -Be 2
        $counts.ContainsKey($other) | Should -BeFalse
        Should -Invoke Invoke-DuneSqlQuery -Times 1 -ParameterFilter {$ReadOnly -and $Sql -match 'online_status' -and $Sql -notmatch ('B'*22)}
    }
    It 'does not turn a failed database observation into a zero-player result' {
        Mock Invoke-DuneSqlQuery {@{ok=$false}}
        $metadata=@{database=@{health='healthy';state='running'};services=@(@{component='game-1';state='running';gameServerId=('A'*22)})}
        (Get-DuneDockerPlayerCounts -Metadata $metadata).Count | Should -Be 0
    }
}
