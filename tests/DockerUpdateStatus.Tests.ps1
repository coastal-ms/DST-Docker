BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerManager.ps1'
    Import-DstLib 'RestartSchedule.ps1'
    Import-DstLib 'Commands.ps1'
    function Invoke-WithDuneLock {param($Name,$Script); & $Script}
}
Describe 'Native manual update and recorded recovery dispatch' {
    BeforeEach {
        Mock Invoke-DuneDockerManager {@{ok=$true;data=@{operation=@{id=('a'*32)}}}}
        Mock Get-DuneDockerFuncomUpdateStatus {@{ok=$true;installedBuild='120';latestBuild='121'}}
    }
    It 'dispatches the checked official build and explicit online authorization' {
        $reply=Start-DuneDockerFuncomUpdate -AllowOnline $true
        $reply.ok|Should -BeTrue
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'updates.apply' -and $Request.expectedBuild -ceq '121' -and $Request.allowOnline -eq $true}
    }
    It 'does not start an update on a metadata outage or downgrade' -TestCases @(
        @{version=@{ok=$false;message='Metadata unavailable'}},
        @{version=@{ok=$true;installedBuild='122';latestBuild='121'}}
    ) {
        param($version)
        Mock Get-DuneDockerFuncomUpdateStatus {$version}
        (Start-DuneDockerFuncomUpdate).ok|Should -BeFalse
        Should -Invoke Invoke-DuneDockerManager -Times 0
    }
    It 'recovers the recorded operation without querying or staging another build' {
        (Start-DuneDockerFuncomUpdate -Recover).ok|Should -BeTrue
        Should -Invoke Get-DuneDockerFuncomUpdateStatus -Times 0
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'updates.recover'}
    }
    It 'keeps update and diagnostics available for recovery while blocking unrelated writes' {
        $state=@{hostingBackend='docker';prepared=$true;desiredState='stopped';maintenance=$true;updateRecovery=$true}
        foreach($name in @('update','logs-export','operator-logs-export')){
            (Get-DuneCommandAvailability -Command @{Name=$name} -State $state).available|Should -BeTrue
        }
        (Get-DuneCommandAvailability -Command @{Name='start'} -State $state).available|Should -BeFalse
        (Get-DuneCommandAvailability -Command @{Name='update-with-tanks'} -State $state).available|Should -BeFalse
        $state.operation=@{phase='running'}
        (Get-DuneCommandAvailability -Command @{Name='update'} -State $state).available|Should -BeFalse
    }
}
Describe 'Native non-destructive Funcom update checks' {
    BeforeEach {
        Mock Invoke-DuneDockerManager {@{ok=$true;data=@{appId='4754530';installedBuild='120'}}}
        Mock Invoke-RestMethod {@{data=@{'4754530'=@{depots=@{branches=@{public=@{buildid='121'}}}}}}}
        Mock Get-DuneRestartSchedule {Get-DuneRestartScheduleDefault}
        Mock Save-DuneRestartSchedule {}
        $script:oldBackend=$env:DST_HOSTING_BACKEND
        $env:DST_HOSTING_BACKEND='docker'
    }
    AfterEach {$env:DST_HOSTING_BACKEND=$script:oldBackend}
    It 'compares the fixed official package and persists metadata without changing schedule settings' {
        Mock Get-DuneRestartSchedule {$s=Get-DuneRestartScheduleDefault;$s.enabled=$true;$s.time='05:30';$s.timeZone='Europe/London';$s}
        $r=Get-DuneFuncomServerUpdateStatus -Persist
        $r.ok|Should -BeTrue
        $r.available|Should -BeTrue
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'assets.version'}
        Should -Invoke Save-DuneRestartSchedule -Times 1 -ParameterFilter {$State.enabled -and $State.time -eq '05:30' -and $State.timeZone -eq 'Europe/London' -and $State.latestBuild -eq '121'}
    }
    It 'reports equal versions without persisting unless requested' {
        Mock Invoke-RestMethod {@{data=@{'4754530'=@{depots=@{branches=@{public=@{buildid='120'}}}}}}}
        $r=Get-DuneDockerFuncomUpdateStatus
        $r.ok|Should -BeTrue
        $r.available|Should -BeFalse
        Should -Invoke Save-DuneRestartSchedule -Times 0
    }
    It 'rejects missing upstream version metadata without overwriting the last successful result' {
        Mock Invoke-RestMethod {@{data=@{}}}
        $r=Get-DuneDockerFuncomUpdateStatus -Persist
        $r.status|Should -Be 502
        $r.ok|Should -BeFalse
        Should -Invoke Save-DuneRestartSchedule -Times 0
    }
    It 'does not query upstream when the installed package identity is invalid' {
        Mock Invoke-DuneDockerManager {@{ok=$true;data=@{appId='12';installedBuild='120'}}}
        $r=Get-DuneDockerFuncomUpdateStatus -Persist
        $r.ok|Should -BeFalse
        Should -Invoke Invoke-RestMethod -Times 0
        Should -Invoke Save-DuneRestartSchedule -Times 0
    }
    It 'keeps an upstream outage as an error rather than reporting up to date' {
        Mock Invoke-RestMethod {throw 'Metadata service unavailable'}
        $r=Get-DuneDockerFuncomUpdateStatus -Persist
        $r.ok|Should -BeFalse
        $r.message|Should -Match 'unavailable'
        Should -Invoke Save-DuneRestartSchedule -Times 0
    }
}
