function Write-DuneDockerSchedulerJson {
    param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)]$Value)
    $parent=Split-Path -Parent $Path
    [void][IO.Directory]::CreateDirectory($parent)
    $temporary=$Path+'.'+[guid]::NewGuid().ToString('N')+'.tmp'
    try {
        $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($Value|ConvertTo-Json -Depth 12))
        $stream=[IO.FileStream]::new($temporary,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        try {$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
        if($IsLinux){[IO.File]::SetUnixFileMode($temporary,([IO.UnixFileMode]::UserRead -bor [IO.UnixFileMode]::UserWrite))}
        [IO.File]::Move($temporary,$Path,$true)
    }finally{if(Test-Path -LiteralPath $temporary){Remove-Item -LiteralPath $temporary -Force}}
}

function Get-DuneDockerRestartJournalPath {
    Join-Path (Split-Path -Parent (Get-DuneRestartStatePath)) 'docker-restart-run.json'
}

function Get-DuneDockerSchedulerHealthPath {
    Join-Path (Split-Path -Parent (Get-DuneRestartStatePath)) 'docker-scheduler-health.json'
}

function Get-DuneDockerSchedulerHealth {
    try{
        $health=Get-Content -LiteralPath (Get-DuneDockerSchedulerHealthPath) -Raw -ErrorAction Stop|ConvertFrom-Json -ErrorAction Stop
        $age=([DateTimeOffset]::UtcNow-[DateTimeOffset]$health.lastTickUtc).TotalSeconds
        $alive=$health.running -eq $true -and $age -ge 0 -and $age -lt 90
        $healthy=$alive -and -not $health.error
        return @{healthy=$healthy;alive=$alive;message=$(if($health.error){[string]$health.error}elseif($healthy){'The Docker service is running the schedule independently of your browser.'}else{'The Docker schedule worker is unavailable. Check the Docker service before enabling scheduled restarts.'})}
    }catch{return @{healthy=$false;alive=$false;message='The Docker schedule worker is starting or unavailable. Try again after the Docker service is ready.'}}
}

function Read-DuneDockerRestartJournal {
    $path=Get-DuneDockerRestartJournalPath
    if(-not(Test-Path -LiteralPath $path)){return @{}}
    $value=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json -AsHashtable -ErrorAction Stop
    if($value -isnot [hashtable] -or $value.date -notmatch '^\d{4}-\d{2}-\d{2}$' -or
        $value.phase -notin @('dispatching','running','completed','failed','skipped','deferred')){
        throw 'The persisted Docker restart record needs review. Automatic restart was blocked.'
    }
    if($value.phase -in @('dispatching','running') -and
        ($value.requestId -notmatch '^[a-f0-9]{32}$' -or $value.startedAt -isnot [ValueType] -or [double]$value.startedAt -lt 0 -or
         ($value.phase -eq 'running' -and $value.operationId -notmatch '^[a-f0-9]{32}$'))){
        throw 'The persisted Docker restart identity needs review. Automatic restart was blocked.'
    }
    return $value
}

function Save-DuneDockerRestartJournal {
    param([hashtable]$Value)
    Write-DuneDockerSchedulerJson -Path (Get-DuneDockerRestartJournalPath) -Value $Value
}

function Get-DuneDockerRestartWindow {
    param([Parameter(Mandatory)]$State,[DateTimeOffset]$Now=[DateTimeOffset]::UtcNow)
    if($State.time -notmatch '^([01]\d|2[0-3]):([0-5]\d)$'){throw 'The scheduled restart time is invalid.'}
    if(-not $State.timeZone){throw 'Select a time zone for scheduled restarts before enabling the schedule.'}
    $zone=[TimeZoneInfo]::FindSystemTimeZoneById([string]$State.timeZone)
    $local=[TimeZoneInfo]::ConvertTime($Now,$zone)
    $makeSlot={param([DateTime]$day)
        $at=[DateTime]::SpecifyKind($day.AddHours([int]$State.time.Substring(0,2)).AddMinutes([int]$State.time.Substring(3,2)),[DateTimeKind]::Unspecified)
        # A repeated wall time names its first occurrence. The journal then
        # prevents a second restart when the clock moves back over that hour.
        $offset=if($zone.IsAmbiguousTime($at)){@($zone.GetAmbiguousTimeOffsets($at)|Sort-Object Ticks -Descending)[0]}else{$zone.GetUtcOffset($at)}
        $instant=[DateTimeOffset]::new($at,$offset).ToUniversalTime()
        @{date=$at.ToString('yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture);now=$local.DateTime;nowUtc=$Now.ToUniversalTime();at=$at;atUtc=$instant;
            leadUtc=$instant.AddMinutes(-[int]$State.broadcastLeadMinutes);endUtc=$instant.AddMinutes(30);timeZone=$zone.Id;invalid=$zone.IsInvalidTime($at)}
    }
    $slot=& $makeSlot $local.Date
    if($Now -gt $slot.endUtc){
        $tomorrow=& $makeSlot $local.Date.AddDays(1)
        if(-not $tomorrow.invalid -and $Now -ge $tomorrow.leadUtc -and $Now -lt $tomorrow.atUtc){$slot=$tomorrow}
    }
    return $slot
}

function Complete-DuneDockerScheduledRestart {
    param([hashtable]$Run,$State,$Metadata,[DateTimeOffset]$Now=[DateTimeOffset]::UtcNow)
    if($Run.phase -eq 'dispatching'){
        # A crash between dispatch and recording its returned identity is
        # ambiguous. Reconcile only the single new restart from that interval.
        $operation=$Metadata.operation
        if($operation.action -eq 'services.restart' -and $operation.requestId -eq $Run.requestId){
            $Run.operationId=$operation.id;$Run.phase='running'
            Save-DuneDockerRestartJournal $Run
        }else{
            $State.lastResult='Scheduled restart dispatch needs review; no duplicate was issued.'
            Save-DuneRestartSchedule $State
            return
        }
    }
    if($Run.phase -ne 'running'){return}
    $operation=$Metadata.operation
    if($operation.id -ne $Run.operationId){
        $Run.phase='failed';$State.lastResult='Scheduled restart completion could not be verified because another operation replaced it.'
    }elseif($operation.phase -in @('failed','interrupted')){
        $Run.phase='failed';$State.lastResult='Scheduled restart failed: '+[string]$operation.error
    }elseif($operation.phase -eq 'completed'){
        $expected=@($Metadata.services|Where-Object {$_.component -match '^game-\d+$' -and $_.desiredState -eq 'running'})
        $unready=@($expected|Where-Object {$_.state -ne 'running' -or $_.gameReady -ne $true})
        $core=@($Metadata.services|Where-Object {$_.component -in @('director','text-router','gateway') -and $_.state -eq 'running'})
        $queues=@($Metadata.connectionServices|Where-Object {$_.health -eq 'healthy'})
        if($expected.Count -gt 0 -and $unready.Count -eq 0 -and $core.Count -eq 3 -and $queues.Count -eq 2 -and $Metadata.database.health -eq 'healthy'){
            $Run.phase='completed';$State.lastResult='Scheduled Docker restart completed; selected maps are game-ready.'
        }elseif($Now.ToUnixTimeSeconds()-[double]$Run.startedAt -gt 900){
            $Run.phase='failed';$State.lastResult='Scheduled restart has not reached game readiness after 15 minutes. Check Server Overview.'
        }else{return}
    }else{return}
    $Run.finishedAt=$Now.ToUnixTimeSeconds()
    $State.lastRestartDate=$Run.date;$State.lastRestartRevision=[string]$Run.scheduleRevision
    Save-DuneDockerRestartJournal $Run
    Save-DuneRestartSchedule $State
}

function Invoke-DuneDockerRestartScheduleTick {
    param([DateTimeOffset]$Now=[DateTimeOffset]::UtcNow)
    Invoke-WithDuneLock -Name 'docker-restart-schedule' -Script {
        $state=Get-DuneRestartSchedule
        $run=Read-DuneDockerRestartJournal
        if(-not $state.enabled -and $run.phase -notin @('dispatching','running')){return}
        if($run.phase -notin @('dispatching','running')){
            $window=Get-DuneDockerRestartWindow -State $state -Now $Now
            $revision=[string]$state.scheduleRevision
            if(($state.lastRestartDate -eq $window.date -and [string]$state.lastRestartRevision -eq $revision) -or
                ($run.date -eq $window.date -and [string]$run.scheduleRevision -eq $revision -and $run.phase -ne 'deferred')){return}
            if($window.invalid){
                if($window.now -ge $window.at){
                    $state.lastRestartDate=$window.date;$state.lastRestartRevision=$revision
                    $state.lastResult='Scheduled time does not exist today because of daylight saving time; skipped.'
                    Save-DuneRestartSchedule $state
                }
                return
            }
            if($state.configuredAtUtc -and [DateTimeOffset]$state.configuredAtUtc -gt $window.atUtc){return}
            if($Now -gt $window.endUtc){
                if($run.phase -eq 'deferred' -and $run.date -eq $window.date -and [string]$run.scheduleRevision -eq $revision){
                    $run.phase='skipped';$state.lastRestartDate=$window.date;$state.lastRestartRevision=$revision
                    $state.lastResult='Scheduled restart skipped because another operation occupied the maintenance window.'
                    Save-DuneDockerRestartJournal $run;Save-DuneRestartSchedule $state
                }
                return
            }
            if($Now -lt $window.leadUtc){return}
        }
        $reply=Invoke-DuneDockerManager -Request @{action='status'}
        if(-not $reply.ok){throw $reply.error}
        $metadata=$reply.data
        if($run.phase -in @('dispatching','running')){
            Complete-DuneDockerScheduledRestart -Run $run -State $state -Metadata $metadata -Now $Now
            return
        }
        if(-not $state.enabled){return}
        # The installation's manager serializes native backups, restores,
        # updates and lifecycle operations. Leave a busy day unconsumed so the
        # next tick can retry within the same maintenance window.
        $activeBackups=@($metadata.backups|Where-Object {$_.phase -in @('preparing','running') -or $_.verification.phase -in @('preparing','running')})
        $busy=$metadata.operation.phase -eq 'running' -or $activeBackups.Count -gt 0 -or $metadata.restore.phase -in @('stopping','preparing','restoring','recovering','recovery-required')
        if($busy -and $Now -ge $window.atUtc){
            if($run.phase -ne 'deferred' -or $run.date -ne $window.date -or [string]$run.scheduleRevision -ne $revision){
                $run=@{date=$window.date;phase='deferred';scheduleRevision=$revision}
                $state.lastResult='Scheduled restart deferred until the current server operation finishes.'
                Save-DuneDockerRestartJournal $run;Save-DuneRestartSchedule $state
            }
            return
        }
        if($metadata.operation.phase -eq 'running'){return}
        if($metadata.desiredState -ne 'running'){
            if($Now -ge $window.atUtc){
                $state.lastRestartDate=$window.date;$state.lastRestartRevision=$revision;$state.lastResult='Scheduled restart skipped because the battlegroup was deliberately stopped.'
                Save-DuneRestartSchedule $state
            }
            return
        }
        if($Now -ge $window.leadUtc -and $Now -lt $window.atUtc -and
            ($state.lastBroadcastDate -ne $window.date -or [string]$state.lastBroadcastRevision -ne $revision)){
            $state.lastBroadcastDate=$window.date;$state.lastBroadcastRevision=$revision
            Save-DuneRestartSchedule $state
            $minutes=[int][Math]::Ceiling(($window.atUtc-$Now).TotalMinutes)
            if($minutes -gt 0){
                $word=ConvertTo-DuneNumberWords $minutes;$unit=if($minutes -eq 1){'minute'}else{'minutes'}
                $null=Send-V6GenericBroadcast -Title 'Game Server Restart' -Body "The game server will be restarting in $word $unit for our scheduled daily BG maintenance." -DurationSec 10
                if($state.discordEnabled -and $state.discordWebhookUrl -and
                    ($state.lastDiscordNoticeDate -ne $window.date -or [string]$state.lastDiscordNoticeRevision -ne $revision)){
                    $state.lastDiscordNoticeDate=$window.date;$state.lastDiscordNoticeRevision=$revision;Save-DuneRestartSchedule $state
                    $null=Send-DuneDiscordWebhook -Url $state.discordWebhookUrl -ServerName $metadata.profile.name -MinutesToRestart $minutes -RestartAt $window.atUtc.UtcDateTime -Reason 'Scheduled daily BG maintenance' -MentionId $state.discordMentionId
                }
            }
        }
        if($Now -lt $window.atUtc -or $Now -gt $window.endUtc){return}
        if($state.applyFuncomUpdates){throw 'Native scheduled Funcom updates are not qualified yet; the scheduled restart was blocked.'}
        $synced=Sync-DuneStartupConsoleVariableOverrides -Ip docker
        if($synced.Success -ne $true){throw 'Scheduled startup settings could not be verified; no restart was issued.'}
        $run=@{date=$window.date;phase='dispatching';startedAt=$Now.ToUnixTimeSeconds();requestId=[guid]::NewGuid().ToString('N');timeZone=$window.timeZone;scheduleRevision=$revision}
        Save-DuneDockerRestartJournal $run
        $reply=Invoke-DuneDockerManager -Request @{action='services.restart';requestId=$run.requestId}
        if(-not $reply.ok -and $reply.code -eq 'operation-busy'){
            $run.phase='deferred';$state.lastResult='Scheduled restart deferred until the current server operation finishes.'
            Save-DuneDockerRestartJournal $run;Save-DuneRestartSchedule $state
            return
        }
        if(-not $reply.ok){
            $run.phase='failed';$state.lastResult='Scheduled restart was rejected: '+[string]$reply.error
        }elseif($reply.data.operation.id -notmatch '^[a-f0-9]{32}$'){
            $state.lastResult='Scheduled restart dispatch needs review; operation identity was not returned.'
        }else{
            $run.phase='running';$run.operationId=$reply.data.operation.id
            $state.lastResult='Scheduled Docker restart started; waiting for game readiness.'
        }
        $state.lastRestartDate=$window.date
        $state.lastRestartRevision=$revision
        Save-DuneDockerRestartJournal $run
        Save-DuneRestartSchedule $state
    }|Out-Null
}

function Start-DuneDockerRestartScheduler {
    param([Parameter(Mandatory)][string]$ServerDir,[Threading.ManualResetEventSlim]$HttpReady)
    if($script:DuneRestartSchedulerStarted){return}
    if(-not $script:DuneApiLockTable){$script:DuneApiLockTable=[hashtable]::Synchronized(@{})}
    $cancel=[Threading.CancellationTokenSource]::new()
    $runspace=[runspacefactory]::CreateRunspace((New-DuneSchedulerInitialSessionState -ServerDir $ServerDir -DeferLibraryLoad))
    $runspace.Name='DuneDockerRestartScheduler';$runspace.Open()
    $pipeline=[powershell]::Create();$pipeline.Runspace=$runspace
    [void]$pipeline.AddScript({param($ServerDir,$Ready,$Token,$Locks)
        if($Ready){$Ready.Wait($Token)}
        . (Join-Path $ServerDir 'HttpServer.ps1')
        foreach($source in $DuneSchedulerStartupScripts){$Token.ThrowIfCancellationRequested();. $source}
        $script:DuneApiLockTable=$Locks
        if($DuneSchedulerLogPath){Set-DuneLogPath -Path $DuneSchedulerLogPath}
        try {
            while(-not $Token.IsCancellationRequested){
                $health=@{running=$true;lastTickUtc=[DateTimeOffset]::UtcNow.ToString('o');error=''}
                try {Invoke-DuneDockerRestartScheduleTick}catch{$health.error=$_.Exception.Message;Write-DuneLog ('Docker restart scheduler: '+$_.Exception.Message) 'WARN'}
                try {Invoke-DuneDiscordStateMonitorTick}catch{Write-DuneLog ('Docker state notifications: '+$_.Exception.Message) 'WARN'}
                Write-DuneDockerSchedulerJson -Path (Get-DuneDockerSchedulerHealthPath) -Value $health
                if($Token.WaitHandle.WaitOne(30000)){break}
            }
        } finally {
            Write-DuneDockerSchedulerJson -Path (Get-DuneDockerSchedulerHealthPath) -Value @{running=$false;lastTickUtc=[DateTimeOffset]::UtcNow.ToString('o');error=''}
        }
    }).AddArgument($ServerDir).AddArgument($HttpReady).AddArgument($cancel.Token).AddArgument($script:DuneApiLockTable)
    try{
        $handle=$pipeline.BeginInvoke()
        $script:DuneRestartSchedulerRunspace=$runspace;$script:DuneRestartSchedulerPowerShell=$pipeline
        $script:DuneRestartSchedulerHandle=$handle;$script:DuneRestartSchedulerCancellation=$cancel;$script:DuneRestartSchedulerStarted=$true
    }catch{$pipeline.Dispose();$runspace.Dispose();$cancel.Dispose();throw}
}
