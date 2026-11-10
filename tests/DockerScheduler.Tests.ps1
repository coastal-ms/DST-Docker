BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerScheduler.ps1'
    Import-DstLib 'RestartSchedule.ps1'
    function global:Invoke-WithDuneLock {param($Name,$Script);& $Script}
    function global:Invoke-DuneDockerManager {param($Request)}
    function global:Sync-DuneStartupConsoleVariableOverrides {param($Ip)}
    function global:Send-V6GenericBroadcast {param($Title,$Body,$DurationSec)}
    function global:Get-DuneDockerStatus {param([switch]$LifecycleOnly)}
    function global:Get-DuneDockerFuncomUpdateStatus {}
}

Describe 'Native daily maintenance execution' {
    BeforeEach {
        $script:oldBackend=$env:DST_HOSTING_BACKEND;$script:oldLocal=$env:LOCALAPPDATA
        $env:DST_HOSTING_BACKEND='docker';$env:LOCALAPPDATA=Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        $script:metadata=@{desiredState='running';profile=@{name='Fixture'};operation=@{id=('a'*32);action='services.start';phase='completed'};
            database=@{state='running';health='healthy'};connectionServices=@(@{health='healthy'},@{health='healthy'});
            services=@(@{component='director';state='running'},@{component='gateway';state='running'},@{component='text-router';state='running'},
                @{component='game-1';state='running';gameReady=$true;desiredState='running'})}
        $state=Get-DuneRestartScheduleDefault;$state.enabled=$true;$state.timeZone='America/Los_Angeles';Save-DuneRestartSchedule $state
        Mock Sync-DuneStartupConsoleVariableOverrides {@{Success=$true}}
        Mock Get-DuneDockerFuncomUpdateStatus {@{ok=$true;available=$true;installedBuild='120';latestBuild='121';checkedAt='2026-11-10T12:00:00Z'}}
        Mock Send-V6GenericBroadcast {@{ok=$true}}
        Mock Send-DuneDiscordWebhook {@{ok=$true}}
        Mock Send-DuneDiscordEmbed {@{ok=$true}}
        Mock Invoke-DuneDockerManager {
            param($Request)
            if($Request.action -in @('services.restart','updates.apply')){
                $script:metadata.operation=@{id=('b'*32);action=$Request.action;phase='running';requestId=$Request.requestId;expectedBuild=$Request.expectedBuild}
                $script:metadata.services[-1].gameReady=$false
            }
            return @{ok=$true;data=$script:metadata}
        }
    }
    AfterEach {$env:DST_HOSTING_BACKEND=$script:oldBackend;$env:LOCALAPPDATA=$script:oldLocal}

    It 'dispatches one correlated native update for an opted-in schedule and waits for readiness' {
        $state=Get-DuneRestartSchedule;$state.applyFuncomUpdates=$true;Save-DuneRestartSchedule $state
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:00Z')
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:30Z')
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'updates.apply' -and $Request.expectedBuild -ceq '121' -and $Request.allowOnline -eq $true -and $Request.requestId -match '^[a-f0-9]{32}$'}
        Should -Invoke Invoke-DuneDockerManager -Times 0 -ParameterFilter {$Request.action -eq 'services.restart'}
        $run=Read-DuneDockerRestartJournal;$run.operationAction|Should -Be 'updates.apply';$run.expectedBuild|Should -BeExactly '121'
        $script:metadata.operation.phase='completed';$script:metadata.services[-1].gameReady=$true
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:02:00Z')
        (Read-DuneDockerRestartJournal).phase|Should -Be 'completed'
        (Get-DuneRestartSchedule).lastResult|Should -Match 'update completed.*game-ready'
    }

    It 'uses the normal restart when an opted-in update check finds the installed build current' {
        $state=Get-DuneRestartSchedule;$state.applyFuncomUpdates=$true;Save-DuneRestartSchedule $state
        Mock Get-DuneDockerFuncomUpdateStatus {@{ok=$true;available=$false;installedBuild='121';latestBuild='121';checkedAt='2026-11-10T12:00:00Z'}}
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:00Z')
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'services.restart'}
        Should -Invoke Invoke-DuneDockerManager -Times 0 -ParameterFilter {$Request.action -eq 'updates.apply'}
    }

    It 'leaves the world untouched when the opted-in update build cannot be checked' {
        $state=Get-DuneRestartSchedule;$state.applyFuncomUpdates=$true;Save-DuneRestartSchedule $state
        Mock Get-DuneDockerFuncomUpdateStatus {@{ok=$false;message='Metadata unavailable'}}
        {Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:00Z')}|Should -Throw '*before stopping*'
        Should -Invoke Sync-DuneStartupConsoleVariableOverrides -Times 0
        Should -Invoke Invoke-DuneDockerManager -Times 0 -ParameterFilter {$Request.action -in @('services.restart','updates.apply')}
    }

    It 'broadcasts once before the configured time and dispatches one correlated restart' {
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T11:51:00Z')
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T11:52:00Z')
        Should -Invoke Send-V6GenericBroadcast -Times 1
        Should -Invoke Invoke-DuneDockerManager -Times 0 -ParameterFilter {$Request.action -eq 'services.restart'}
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:00Z')
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:30Z')
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'services.restart' -and $Request.requestId -match '^[a-f0-9]{32}$'}
        (Read-DuneDockerRestartJournal).phase|Should -Be 'running'
    }

    It 'requires fresh game readiness before reporting a completed restart' {
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:00Z')
        $script:metadata.operation.phase='completed'
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:01:00Z')
        (Read-DuneDockerRestartJournal).phase|Should -Be 'running'
        $script:metadata.services[-1].gameReady=$true
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:02:00Z')
        (Read-DuneDockerRestartJournal).phase|Should -Be 'completed'
        (Get-DuneRestartSchedule).lastResult|Should -Match 'game-ready'
    }

    It 'does not report readiness while the database or connection queues are unhealthy' {
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:00Z')
        $script:metadata.operation.phase='completed';$script:metadata.services[-1].gameReady=$true;$script:metadata.database.health='unhealthy'
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:01:00Z')
        (Read-DuneDockerRestartJournal).phase|Should -Be 'running'
        $script:metadata.database.health='healthy';$script:metadata.connectionServices[0].health='unhealthy'
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:02:00Z')
        (Read-DuneDockerRestartJournal).phase|Should -Be 'running'
        $script:metadata.connectionServices[0].health='healthy'
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:03:00Z')
        (Read-DuneDockerRestartJournal).phase|Should -Be 'completed'
    }

    It 'defers a restart while a backup is running without consuming the day' {
        $script:metadata.operation.phase='running';$script:metadata.operation.action='backups.create'
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:00Z')
        (Get-DuneRestartSchedule).lastRestartDate|Should -Be ''
        $script:metadata.operation.phase='completed'
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:05:00Z')
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'services.restart'}
    }

    It 'does not start an intentionally stopped world' {
        $script:metadata.desiredState='stopped'
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:00Z')
        Should -Invoke Invoke-DuneDockerManager -Times 0 -ParameterFilter {$Request.action -eq 'services.restart'}
        (Get-DuneRestartSchedule).lastResult|Should -Match 'deliberately stopped'
    }

    It 'waits for an asynchronous dump even after its launch operation completed' {
        $script:metadata.backups=@(@{phase='running'})
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:00Z')
        Should -Invoke Invoke-DuneDockerManager -Times 0 -ParameterFilter {$Request.action -eq 'services.restart'}
        (Get-DuneRestartSchedule).lastRestartDate|Should -Be ''
    }

    It 'keeps the configured warning while a dump is running and defers only the restart' {
        $script:metadata.backups=@(@{phase='running'})
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T11:50:00Z')
        Should -Invoke Send-V6GenericBroadcast -Times 1
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:00Z')
        (Read-DuneDockerRestartJournal).phase|Should -Be 'deferred'
        Should -Invoke Invoke-DuneDockerManager -Times 0 -ParameterFilter {$Request.action -eq 'services.restart'}
    }

    It 'records an expired deferred window without polling or restarting later in the day' {
        $script:metadata.backups=@(@{phase='running'})
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:00Z')
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:31:00Z')
        (Read-DuneDockerRestartJournal).phase|Should -Be 'skipped'
        (Get-DuneRestartSchedule).lastResult|Should -Match 'occupied the maintenance window'
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'status'}
        Should -Invoke Invoke-DuneDockerManager -Times 0 -ParameterFilter {$Request.action -eq 'services.restart'}
    }

    It 'does not replay a missed maintenance window' {
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:31:00Z')
        Should -Invoke Invoke-DuneDockerManager -Times 0
    }

    It 'does not restart immediately when a user arms a time that already passed today' {
        $state=Get-DuneRestartSchedule;$state.configuredAtUtc='2026-11-10T12:15:00Z';$state.scheduleRevision=('c'*32);Save-DuneRestartSchedule $state
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:20:00Z')
        Should -Invoke Invoke-DuneDockerManager -Times 0
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-11T12:00:00Z')
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'services.restart'}
    }

    It 'honors a newly selected future time after an earlier completed configuration' {
        $state=Get-DuneRestartSchedule;$state.time='05:00';$state.configuredAtUtc='2026-11-10T12:15:00Z';$state.scheduleRevision=('c'*32)
        $state.lastRestartDate='2026-11-10';$state.lastRestartRevision=('d'*32);Save-DuneRestartSchedule $state
        Save-DuneDockerRestartJournal @{date='2026-11-10';phase='completed';scheduleRevision=('d'*32)}
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T13:00:00Z')
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'services.restart'}
    }

    It 'warns before midnight for the next day and sends the correct absolute Discord time' {
        $state=Get-DuneRestartSchedule;$state.time='00:05';$state.discordEnabled=$true
        $state.discordWebhookUrl='https://discord.com/api/webhooks/123456789012345678/fixture_token_not_real';Save-DuneRestartSchedule $state
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-11T07:55:00Z')
        (Get-DuneRestartSchedule).lastBroadcastDate|Should -Be '2026-11-11'
        Should -Invoke Send-DuneDiscordWebhook -Times 1 -ParameterFilter {$MinutesToRestart -eq 10 -and $RestartAt.Kind -eq [DateTimeKind]::Utc -and $RestartAt.Hour -eq 8 -and $RestartAt.Minute -eq 5}
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-11T08:05:00Z')
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'services.restart'}
        Should -Invoke Send-V6GenericBroadcast -Times 1
    }

    It 'does not extend a deferred maintenance window through the repeated daylight-saving hour' {
        $state=Get-DuneRestartSchedule;$state.time='01:30';Save-DuneRestartSchedule $state
        $script:metadata.backups=@(@{phase='running'})
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-01T08:30:00Z')
        $script:metadata.backups=@()
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-01T09:30:00Z')
        Should -Invoke Invoke-DuneDockerManager -Times 0 -ParameterFilter {$Request.action -eq 'services.restart'}
    }

    It 'does not issue a duplicate after an ambiguous dispatch interruption' {
        Save-DuneDockerRestartJournal @{date='2026-11-10';phase='dispatching';requestId=('c'*32);startedAt=1794312000}
        $script:metadata.operation.action='services.restart';$script:metadata.operation.requestId=('d'*32)
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:00Z')
        Should -Invoke Invoke-DuneDockerManager -Times 0 -ParameterFilter {$Request.action -eq 'services.restart'}
        (Get-DuneRestartSchedule).lastResult|Should -Match 'needs review'
    }

    It 'reconciles only the persisted request identity after a dispatch interruption' {
        Save-DuneDockerRestartJournal @{date='2026-11-10';phase='dispatching';requestId=('c'*32);startedAt=1794312000}
        $script:metadata.operation=@{id=('b'*32);action='services.restart';phase='completed';requestId=('c'*32)}
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:00Z')
        (Read-DuneDockerRestartJournal).phase|Should -Be 'completed'
        Should -Invoke Invoke-DuneDockerManager -Times 0 -ParameterFilter {$Request.action -eq 'services.restart'}
    }

    It 'blocks a corrupt dispatch record rather than treating it as a fresh day' {
        Save-DuneDockerRestartJournal @{date='2026-11-10';phase='dispatching'}
        {Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:00Z')}|Should -Throw '*identity needs review*'
        Should -Invoke Invoke-DuneDockerManager -Times 0
    }

    It 'does not duplicate the daily restart during the repeated daylight-saving hour' {
        $state=Get-DuneRestartSchedule;$state.time='01:30';Save-DuneRestartSchedule $state
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-01T08:30:00Z')
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-01T09:30:00Z')
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'services.restart'}
    }

    It 'skips a nonexistent daylight-saving wall time explicitly' {
        $state=Get-DuneRestartSchedule;$state.time='02:30';Save-DuneRestartSchedule $state
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2027-03-14T10:00:00Z')
        (Get-DuneRestartSchedule).lastResult|Should -Match 'does not exist'
        Should -Invoke Invoke-DuneDockerManager -Times 0 -ParameterFilter {$Request.action -eq 'services.restart'}
    }

    It 'rejects an invalid time zone without saving' {
        $before=Get-Content (Get-DuneRestartStatePath) -Raw
        (Set-DuneRestartSchedule -Enabled $true -Time '04:00' -TimeZone 'not/a/timezone').status|Should -Be 400
        (Get-Content (Get-DuneRestartStatePath) -Raw)|Should -BeExactly $before
    }

    It 'saves explicit automatic update opt-in only when the schedule worker is alive' {
        Write-DuneDockerSchedulerJson -Path (Get-DuneDockerSchedulerHealthPath) -Value @{running=$true;lastTickUtc=[DateTimeOffset]::UtcNow.ToString('o');error=''}
        $result=Set-DuneRestartSchedule -Enabled $true -Time '04:00' -TimeZone 'America/Los_Angeles' -ApplyFuncomUpdates $true
        $result.ok|Should -BeTrue
        (Get-DuneRestartSchedule).applyFuncomUpdates|Should -BeTrue
    }

    It 'does not enable a schedule when its actual worker is unavailable' {
        (Set-DuneRestartSchedule -Enabled $true -Time '04:00' -TimeZone 'America/Los_Angeles').status|Should -Be 503
    }

    It 'rejects an older caller that would silently use the container time zone' {
        Write-DuneDockerSchedulerJson -Path (Get-DuneDockerSchedulerHealthPath) -Value @{running=$true;lastTickUtc=[DateTimeOffset]::UtcNow.ToString('o');error=''}
        $state=Get-DuneRestartSchedule;$state.timeZone='';Save-DuneRestartSchedule $state
        (Set-DuneRestartSchedule -Enabled $true -Time '04:00').status|Should -Be 400
    }

    It 'preserves the selected zone and secret when saving a supported schedule' {
        Write-DuneDockerSchedulerJson -Path (Get-DuneDockerSchedulerHealthPath) -Value @{running=$true;lastTickUtc=[DateTimeOffset]::UtcNow.ToString('o');error=''}
        $state=Get-DuneRestartSchedule;$state.discordWebhookUrl='https://discord.com/api/webhooks/123456789012345678/fixture_token_not_real';Save-DuneRestartSchedule $state
        $result=Set-DuneRestartSchedule -Enabled $true -Time '03:45' -TimeZone 'Europe/London' -BroadcastLeadMinutes 7
        $result.ok|Should -BeTrue
        (Get-DuneRestartSchedule).timeZone|Should -Be 'Europe/London'
        (Get-DuneRestartSchedule).time|Should -Be '03:45'
        (Get-DuneRestartSchedule).discordWebhookUrl|Should -BeExactly $state.discordWebhookUrl
    }

    It 'retries a known busy rejection that occurs after the initial status check' {
        $script:rejectOnce=$true
        Mock Invoke-DuneDockerManager {
            param($Request)
            if($Request.action -eq 'services.restart'){
                if($script:rejectOnce){$script:rejectOnce=$false;return @{ok=$false;code='operation-busy';error='Another server operation is in progress.'}}
                $script:metadata.operation=@{id=('b'*32);action='services.restart';phase='running';requestId=$Request.requestId}
            }
            return @{ok=$true;data=$script:metadata}
        }
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:00:00Z')
        (Read-DuneDockerRestartJournal).phase|Should -Be 'deferred'
        (Get-DuneRestartSchedule).lastRestartDate|Should -Be ''
        Invoke-DuneDockerRestartScheduleTick -Now ([DateTimeOffset]'2026-11-10T12:01:00Z')
        (Read-DuneDockerRestartJournal).phase|Should -Be 'running'
        Should -Invoke Invoke-DuneDockerManager -Times 2 -ParameterFilter {$Request.action -eq 'services.restart'}
    }

    It 'reuses the ready transition notification through native host facts without sending a real webhook' {
        $state=Get-DuneRestartSchedule;$state.discordNotifyOnline=$true;$state.discordWebhookUrl='https://discord.com/api/webhooks/123456789012345678/fixture_token_not_real'
        Save-DuneRestartSchedule $state
        $script:DuneDiscordLastHaggaReady=$false
        Mock Get-DuneDockerStatus {@{host=@{running=$true};bg=@{state='running';title='Fixture';gameServers=@(@{map='Survival_1';phase='Running';ready='True'})}}}
        Invoke-DuneDiscordStateMonitorTick
        Invoke-DuneDiscordStateMonitorTick
        Should -Invoke Send-DuneDiscordEmbed -Times 1
    }

    It 'saves the existing update notification option without enabling automatic updates' {
        $result=Set-DuneRestartSchedule -Enabled $false -Time '04:00' -TimeZone 'UTC' -DiscordNotifyUpdate $true -DiscordWebhookUrl 'https://discord.com/api/webhooks/123456789012345678/fixture_token_not_real'
        $result.ok|Should -BeTrue
        $saved=Get-DuneRestartSchedule
        $saved.discordNotifyUpdate|Should -BeTrue
        $saved.applyFuncomUpdates|Should -BeFalse
        $saved.enabled|Should -BeFalse
    }

    It 'uses the shared update transition once and respects the saved opt-out' {
        $state=Get-DuneRestartSchedule;$state.discordNotifyUpdate=$true
        $state.discordWebhookUrl='https://discord.com/api/webhooks/123456789012345678/fixture_token_not_real'
        $state.installedBuild='120';$state.latestBuild='121';$state.updateAvailable=$false
        Save-DuneRestartSchedule $state
        $script:DuneDiscordLastUpdateAvailable=$null
        Mock Get-DuneDockerStatus {@{host=@{running=$true};bg=@{state='stopped';title='Fixture';gameServers=@()}}}
        Invoke-DuneDiscordStateMonitorTick
        $state.updateAvailable=$true;Save-DuneRestartSchedule $state
        Invoke-DuneDiscordStateMonitorTick
        Invoke-DuneDiscordStateMonitorTick
        Should -Invoke Send-DuneDiscordEmbed -Times 1 -ParameterFilter {$Embed.title -match 'Update' -and $Embed.fields[0].value -eq '120' -and $Embed.fields[1].value -eq '121'}
        $state.updateAvailable=$false;Save-DuneRestartSchedule $state
        Invoke-DuneDiscordStateMonitorTick
        $state.discordNotifyUpdate=$false;$state.updateAvailable=$true;Save-DuneRestartSchedule $state
        Invoke-DuneDiscordStateMonitorTick
        Should -Invoke Send-DuneDiscordEmbed -Times 1
    }
}
