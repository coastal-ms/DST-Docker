BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'VehicleDeletion.ps1'
    Import-DstLib 'Gameplay.ps1'
    function Get-DuneVehicleHostScope { @{key=('a'*64);world=('c'*32)} }
    function Invoke-DuneDockerManager { param($Request); throw 'Manager must be mocked.' }
    function Invoke-DuneSqlQuery { param($Ip,$Sql,$ReadOnly,$MaxRows,$TimeoutSec); throw 'SQL must be mocked.' }
    function Invoke-DuneBackupShell { param($Ip,$Script,$TimeoutSec); throw 'SSH is forbidden in native tests.' }
    function Invoke-DuneDockerServiceLifecycle { param($Command,$TimeoutSec); throw 'Lifecycle must be mocked.' }
    $script:oldHostingBackend=$env:DST_HOSTING_BACKEND
}
AfterAll { $env:DST_HOSTING_BACKEND=$script:oldHostingBackend }
Describe 'Native vehicle deletion transport' {
    BeforeEach {
        $env:DST_HOSTING_BACKEND='docker'
        Mock Invoke-DuneBackupShell { throw 'SSH is forbidden in native tests.' }
        Mock Invoke-DuneDockerServiceLifecycle { throw 'Unexpected lifecycle request.' }
        Mock Invoke-DuneSqlQuery { @{ok=$true;columns=@('sessions');rows=@(,@('0'))} }
        Mock Invoke-DuneDockerManager { @{ok=$true;data=@{projectId=('c'*32);desiredState='stopped';services=@(@{component='game-1';state='exited'},@{component='game-2';state='created'})}} }
    }
    It 'requires stopped owned games and a fresh zero-session database check' {
        (Test-DuneVehicleWindowStopped -Ip docker -DatabaseScope ('a'*64)).ok | Should -BeTrue
        Should -Invoke Invoke-DuneSqlQuery -Times 1 -ParameterFilter {$ReadOnly -and $Sql -match 'pg_stat_activity'}
        Should -Invoke Invoke-DuneBackupShell -Times 0
    }
    It 'rejects missing, running and unknown game observations before SQL' -TestCases @(
        @{State='running'},@{State='paused'},@{State='restarting'},@{State='dead'},@{State=''}
    ) {
        param($State)
        Mock Invoke-DuneDockerManager { @{ok=$true;data=@{projectId=('c'*32);desiredState='stopped';services=@(@{component='game-1';state=$State})}} }
        (Test-DuneVehicleWindowStopped -Ip docker -DatabaseScope ('a'*64)).ok | Should -BeFalse
        Should -Invoke Invoke-DuneSqlQuery -Times 0
    }
    It 'rejects an absent game roster or desired running world' -TestCases @(@{Running=$true},@{Running=$false}) {
        param($Running)
        Mock Invoke-DuneDockerManager { @{ok=$true;data=@{projectId=('c'*32);desiredState=$(if($Running){'running'}else{'stopped'});services=$(if($Running){@(@{component='game-1';state='exited'})}else{@()})}} }
        (Test-DuneVehicleWindowStopped -Ip docker -DatabaseScope ('a'*64)).ok | Should -BeFalse
        Should -Invoke Invoke-DuneSqlQuery -Times 0
    }
    It 'rejects manager failure and world-scope changes before SQL' {
        Mock Invoke-DuneDockerManager { @{ok=$false;error='unavailable'} }
        (Test-DuneVehicleWindowStopped -Ip docker -DatabaseScope ('a'*64)).ok | Should -BeFalse
        (Test-DuneVehicleWindowStopped -Ip docker -DatabaseScope ('b'*64)).ok | Should -BeFalse
        Should -Invoke Invoke-DuneSqlQuery -Times 0
    }
    It 'rejects game sessions even when every game container is stopped' {
        Mock Invoke-DuneSqlQuery { @{ok=$true;columns=@('sessions');rows=@(,@('1'))} }
        (Test-DuneVehicleWindowStopped -Ip docker -DatabaseScope ('a'*64)).ok | Should -BeFalse
    }
    It 'rejects a changed Docker project observation before SQL' {
        Mock Invoke-DuneDockerManager { @{ok=$true;data=@{projectId=('d'*32);desiredState='stopped';services=@(@{component='game-1';state='exited'})}} }
        (Test-DuneVehicleWindowStopped -Ip docker -DatabaseScope ('a'*64)).ok | Should -BeFalse
        Should -Invoke Invoke-DuneSqlQuery -Times 0
    }
    It 'waits for the typed native lifecycle and preserves failures' {
        Mock Invoke-DuneDockerServiceLifecycle { @{ok=$true;output='stopped'} }
        $result=Invoke-DuneVehicleLifecycleCommand -Ip docker -Command stop -TimeoutSec 600
        $result.rc | Should -Be 0
        Should -Invoke Invoke-DuneDockerServiceLifecycle -Times 1 -ParameterFilter {$Command -eq 'stop' -and $TimeoutSec -eq 600}
        Mock Invoke-DuneDockerServiceLifecycle { @{ok=$false;error='restart interrupted'} }
        $result=Invoke-DuneVehicleLifecycleCommand -Ip docker -Command start -TimeoutSec 900
        $result.rc | Should -Be 1
        $result.out | Should -Be 'restart interrupted'
        Should -Invoke Invoke-DuneBackupShell -Times 0
    }
    It 'preserves the existing VM shell command outside Docker' {
        $env:DST_HOSTING_BACKEND='hyperv'
        Mock Invoke-DuneBackupShell { @{rc=0;out='VM stopped'} }
        (Invoke-DuneVehicleLifecycleCommand -Ip fixture -Command stop -TimeoutSec 600).rc | Should -Be 0
        Should -Invoke Invoke-DuneBackupShell -Times 1 -ParameterFilter {$Ip -eq 'fixture' -and $Script -eq '/home/dune/.dune/bin/battlegroup stop' -and $TimeoutSec -eq 600}
        Should -Invoke Invoke-DuneDockerServiceLifecycle -Times 0
    }
}
