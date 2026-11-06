$ErrorActionPreference='Stop'
if(-not(Test-Path '/control/qualification-only')){throw 'This test requires the isolated Unix protocol fixture.'}
$env:DST_HOSTING_BACKEND='docker';$env:LOCALAPPDATA='/tmp/dst-scheduler-dispatch';$env:APPDATA='/tmp/dst-scheduler-config'
. /opt/dst/app/server/HttpServer.ps1
. /opt/dst/app/server/lib/DockerScheduler.ps1
. /opt/dst/app/server/lib/RestartSchedule.ps1
$state=Get-DuneRestartScheduleDefault;$state.enabled=$true;$state.timeZone='UTC';$state.time=[DateTimeOffset]::UtcNow.ToString('HH:mm');$state.broadcastLeadMinutes=0
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
    $restarts=@($events|Where-Object action -eq 'services.restart')
    if($restarts.Count -ne 1 -or $restarts[0].requestId -ne $run.requestId){throw 'The scheduled request was duplicated or lost its persisted identity.'}
    if(@($events|Where-Object action -eq 'settings.startup').Count -ne 1){throw 'The shared startup settings workflow was not executed.'}
    if((Get-DuneRestartSchedule).lastResult -notmatch 'game-ready'){throw 'Game readiness was not reflected in the persisted schedule result.'}
    @{ok=$true;realBackgroundDispatch=$true;restartCount=$restarts.Count;sharedStartupSync=$true;persistedRequestMatched=$true;
        realManagerProtocolFixture=$true;noActualGameRestart=$true;gameReadyObserved=$true}|ConvertTo-Json
}finally{$null=Stop-DuneRestartScheduler;$ready.Dispose()}
