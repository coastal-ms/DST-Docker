$ErrorActionPreference='Stop'
if(Test-Path -LiteralPath '/control/manager.sock'){throw 'Runtime qualification must not have the production manager socket.'}
$env:DST_HOSTING_BACKEND='docker';$env:LOCALAPPDATA='/tmp/dst-scheduler-runtime';$env:APPDATA='/tmp/dst-scheduler-config'
. /opt/dst/app/server/HttpServer.ps1
. /opt/dst/app/server/lib/DockerScheduler.ps1
. /opt/dst/app/server/lib/RestartSchedule.ps1
$clock=Get-DuneDockerRestartWindow -State @{time='04:00';timeZone='America/Los_Angeles';broadcastLeadMinutes=10} -Now ([DateTimeOffset]'2026-11-10T12:00:00Z')
if($clock.now.Hour -ne 4 -or $clock.date -ne '2026-11-10'){throw 'The Linux runtime did not resolve the named schedule time zone.'}
$gap=Get-DuneDockerRestartWindow -State @{time='02:30';timeZone='America/Los_Angeles';broadcastLeadMinutes=0} -Now ([DateTimeOffset]'2027-03-14T10:00:00Z')
if(-not $gap.invalid){throw 'The Linux runtime did not identify the daylight-saving gap.'}
$state=Get-DuneRestartScheduleDefault
$state.enabled=$false
Save-DuneRestartSchedule $state
if($IsLinux -and [IO.File]::GetUnixFileMode((Get-DuneRestartStatePath)) -ne ([IO.UnixFileMode]::UserRead -bor [IO.UnixFileMode]::UserWrite)){
    throw 'Scheduler state is not private to its service user.'
}
$ready=[Threading.ManualResetEventSlim]::new($true)
try {
    Start-DuneDockerRestartScheduler -ServerDir /opt/dst/app/server -HttpReady $ready
    $deadline=[DateTime]::UtcNow.AddSeconds(30)
    do {
        if($script:DuneRestartSchedulerHandle.IsCompleted){
            $null=$script:DuneRestartSchedulerPowerShell.EndInvoke($script:DuneRestartSchedulerHandle)
            throw 'The native scheduler exited before its first completed clock tick.'
        }
        if(Test-Path (Get-DuneDockerSchedulerHealthPath)){$health=Get-Content (Get-DuneDockerSchedulerHealthPath) -Raw|ConvertFrom-Json}
        if($health.running){break}
        Start-Sleep -Milliseconds 100
    }while([DateTime]::UtcNow -lt $deadline)
    if(-not $health.running -or $health.error){throw 'The native scheduler did not complete its disabled idle tick.'}
    if((Get-DuneRestartSchedule).enabled){throw 'The disabled native schedule was unexpectedly enabled.'}
    $timer=[Diagnostics.Stopwatch]::StartNew()
    if(-not(Stop-DuneRestartScheduler)){throw 'The native scheduler did not shut down cleanly.'}
    $timer.Stop()
    $health=Get-Content (Get-DuneDockerSchedulerHealthPath) -Raw|ConvertFrom-Json
    if($health.running -or $timer.ElapsedMilliseconds -gt 3000){throw 'The native scheduler did not observe its cancellation promptly.'}
    @{ok=$true;realRunspaceTick=$true;namedTimeZoneVerified=$true;daylightSavingGapVerified=$true;disabledScheduleUnchanged=$true;productionSocketAbsent=$true;shutdownMs=$timer.ElapsedMilliseconds}|ConvertTo-Json
}finally{
    if($script:DuneRestartSchedulerStarted){$null=Stop-DuneRestartScheduler}
    $ready.Dispose()
}
