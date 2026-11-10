param([switch]$Updates)
$ErrorActionPreference='Stop'
if(-not(Test-Path '/control/qualification-only')){throw 'This test requires the isolated Unix protocol fixture.'}
$env:DST_HOSTING_BACKEND='docker';$env:LOCALAPPDATA='/tmp/dst-scheduler-dispatch';$env:APPDATA='/tmp/dst-scheduler-config'
. /opt/dst/app/server/HttpServer.ps1
. /opt/dst/app/server/lib/DockerScheduler.ps1
. /opt/dst/app/server/lib/RestartSchedule.ps1
$state=Get-DuneRestartScheduleDefault;$state.enabled=$true;$state.timeZone='UTC';$state.time=[DateTimeOffset]::UtcNow.ToString('HH:mm');$state.broadcastLeadMinutes=0
$state.applyFuncomUpdates=[bool]$Updates
if($Updates){
    # The actual background worker loads every real library. Only upstream
    # version metadata is substituted inside this no-network fixture.
    $script:qualificationInitialSessionState=${function:New-DuneSchedulerInitialSessionState}
    function New-DuneSchedulerInitialSessionState {
        param($ServerDir,[switch]$DeferLibraryLoad)
        $initial=& $script:qualificationInitialSessionState -ServerDir $ServerDir -DeferLibraryLoad:$DeferLibraryLoad
        $entry=@($initial.Variables|Where-Object Name -eq 'DuneSchedulerStartupScripts')[0]
        $others=@($initial.Variables|Where-Object Name -ne 'DuneSchedulerStartupScripts')
        $initial.Variables.Clear()
        foreach($other in $others){[void]$initial.Variables.Add($other)}
        [void]$initial.Variables.Add([System.Management.Automation.Runspaces.SessionStateVariableEntry]::new(
            'DuneSchedulerStartupScripts',[string[]](@($entry.Value)+@('/qualification-upstream.ps1')),'Qualification metadata override'))
        return $initial
    }
}
$state.configuredAtUtc=[DateTimeOffset]::UtcNow.AddMinutes(-5).ToString('o');$state.scheduleRevision=[guid]::NewGuid().ToString('N')
Save-DuneRestartSchedule $state
$ready=[Threading.ManualResetEventSlim]::new($true)
try {
    Start-DuneDockerRestartScheduler -ServerDir /opt/dst/app/server -HttpReady $ready
    $deadline=[DateTime]::UtcNow.AddSeconds(65)
    do {
        if($script:DuneRestartSchedulerHandle.IsCompleted){$null=$script:DuneRestartSchedulerPowerShell.EndInvoke($script:DuneRestartSchedulerHandle);throw 'The scheduler exited during dispatch.'}
        $run=Read-DuneDockerRestartJournal
        if($run.phase -eq 'completed'){break}
        if($run.phase -eq 'failed'){throw 'The isolated scheduled operation failed.'}
        Start-Sleep -Milliseconds 250
    }while([DateTime]::UtcNow -lt $deadline)
    if($run.phase -ne 'completed'){
        $health=Get-DuneDockerSchedulerHealth
        throw ('The isolated scheduled operation did not complete: '+$health.message)
    }
    $events=@(Get-Content /control/events.json -Raw|ConvertFrom-Json)
    $action=if($Updates){'updates.apply'}else{'services.restart'}
    $restarts=@($events|Where-Object action -eq $action)
    if($restarts.Count -ne 1 -or $restarts[0].requestId -ne $run.requestId){throw 'The scheduled request was duplicated or lost its persisted identity.'}
    if($Updates -and ($restarts[0].expectedBuild -cne '121' -or $restarts[0].allowOnline -ne $true -or $run.expectedBuild -cne '121')){throw 'The native update lost its exact checked build or schedule authorization.'}
    if(@($events|Where-Object action -eq 'settings.startup').Count -ne 1){throw 'The shared startup settings workflow was not executed.'}
    if((Get-DuneRestartSchedule).lastResult -notmatch 'game-ready'){throw 'Game readiness was not reflected in the persisted schedule result.'}
    @{ok=$true;realBackgroundDispatch=$true;restartCount=$restarts.Count;sharedStartupSync=$true;persistedRequestMatched=$true;
        realManagerProtocolFixture=$true;nativeUpdateDispatch=[bool]$Updates;noActualGameRestart=$true;gameReadyObserved=$true}|ConvertTo-Json
}finally{$null=Stop-DuneRestartScheduler;$ready.Dispose()}
