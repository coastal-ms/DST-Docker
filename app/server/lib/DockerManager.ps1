function Get-DuneDockerGamePhase {
    param($Service,$Operation)
    $partition=[int]([string]$Service.component).Substring(5)
    $active=$Operation.phase -eq 'running'
    $stopping=$Service.desiredState -eq 'stopped' -or ($active -and ($Operation.action -eq 'services.stop' -or ($Operation.action -eq 'maps.stop' -and $Operation.partition -eq $partition)))
    if($Service.state -in @('running','restarting') -and $stopping){return 'Unloading'}
    if($Service.state -eq 'running'){
        if($Service.gameReady -eq $true){return 'Running'}
        if($active -and ($Operation.action -eq 'services.start' -or ($Operation.action -in @('maps.start','maps.restart') -and $Operation.partition -eq $partition))){return 'Loading'}
        return 'Configuring'
    }
    if($Service.state -eq 'restarting'){return 'Loading'}
    if($Service.state -eq 'created'){return 'Pending'}
    if($active -and $Operation.action -eq 'maps.restart' -and $Operation.partition -eq $partition){return 'Loading'}
    return 'Failed'
}

function Get-DuneDockerPlayerCounts {
    param($Metadata)
    $counts=@{}
    $ids=@($Metadata.services | Where-Object {$_.state -eq 'running' -and $_.component -match '^game-[0-9]+$' -and [string]$_.gameServerId -cmatch '^[A-Za-z0-9_+/-]{22}$'} | ForEach-Object {[string]$_.gameServerId} | Sort-Object -Unique)
    if(-not $ids.Count -or $Metadata.database.health -ne 'healthy' -or $Metadata.database.state -ne 'running'){return $counts}
    try {
        $quoted=($ids | ForEach-Object {"'$_'"}) -join ','
        $result=Invoke-DuneSqlQuery -Ip docker -ReadOnly $true -Sql "SELECT server_id::text AS server_id, count(*)::text AS players FROM encrypted_player_state WHERE online_status::text <> 'Offline' AND server_id IN ($quoted) GROUP BY server_id;"
        if(-not $result.ok){return $counts}
        foreach($id in $ids){$counts[$id]=0}
        foreach($row in (ConvertTo-DuneRowMaps -Result $result)){
            if([string]$row.server_id -cin $ids -and [string]$row.players -match '^\d+$'){$counts[[string]$row.server_id]=[int]$row.players}
        }
    } catch {return @{}}
    return $counts
}

function Sync-DuneFuncomInstalledBuild {
    param([string]$InstalledBuild)
    if ($InstalledBuild -notmatch '^\d+$') { return $false }
    $sync = {
        $state = Get-DuneRestartSchedule
        $available = [bool]$state.updateAvailable
        if ([string]$state.latestBuild -match '^\d+$') {
            $available = ([int64]$state.latestBuild -gt [int64]$InstalledBuild)
        }
        if ([string]$state.installedBuild -eq $InstalledBuild -and $state.updateAvailable -eq $available) { return $false }
        $state.installedBuild = $InstalledBuild
        $state.updateAvailable = $available
        # Prevent an older maintenance result or in-flight check from restoring
        # the pre-update build after this newer installed-build observation.
        $state.updateCheckedAt = (Get-Date).ToString('o')
        Save-DuneRestartSchedule -State $state
        return $true
    }
    if (Get-Command Invoke-WithDuneLock -ErrorAction SilentlyContinue) {
        return Invoke-WithDuneLock -Name 'docker-restart-schedule' -TimeoutSec 5 -Script $sync
    }
    return & $sync
}


function Invoke-DuneDockerManager {
    param([Parameter(Mandatory)][hashtable]$Request,[switch]$HostSession)
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = 'python3'
    $client=if($HostSession){'host-client.py'}else{'manager-client.py'}
    [void]$start.ArgumentList.Add("/opt/dst/packaging/docker/$client")
    $start.UseShellExecute = $false
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardInputEncoding = [Text.UTF8Encoding]::new($false)
    $start.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    try {
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $process.StandardInput.Write(($Request | ConvertTo-Json -Compress -Depth 16))
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(45000)) { $process.Kill($true); throw 'Docker management request timed out.' }
        if ($process.ExitCode -ne 0) { throw 'Docker management service is unavailable.' }
        return $stdout.GetAwaiter().GetResult() | ConvertFrom-Json -AsHashtable
    } finally { $process.Dispose() }
}

function Get-DuneDockerFuncomUpdateStatus {
    param([switch]$Persist)
    $checkedAt=[DateTimeOffset]::UtcNow.ToString('o')
    try {
        $reply=Invoke-DuneDockerManager -Request @{action='assets.version'}
        if(-not $reply.ok){throw 'The official installed Steam manifest could not be read.'}
        $installed=[string]$reply.data.installedBuild
        if($reply.data.appId -cne '4754530' -or $installed -notmatch '^\d{1,18}$'){throw 'The installed self-host package version is invalid.'}
        # Same public metadata service used by the existing VM update check.
        # Checking never downloads/replaces assets or restarts any service.
        $info=Invoke-RestMethod -Uri 'https://api.steamcmd.net/v1/info/4754530' -TimeoutSec 8 -ErrorAction Stop
        $latest=[string]$info.data.'4754530'.depots.branches.public.buildid
        if($latest -notmatch '^\d{1,18}$' -or [long]$latest -le 0){throw 'The public update service did not return a valid self-host build.'}
        $available=[long]$latest -gt [long]$installed
        $result=@{ok=$true;available=$available;installedBuild=$installed;latestBuild=$latest;checkedAt=$checkedAt;source='api';
            message=$(if($available){"Funcom server update available (installed $installed, latest $latest)."}else{"Server is up to date (build $installed)."})}
        if($Persist){
            Invoke-WithDuneLock -Name 'docker-restart-schedule' -Script {
                $state=Get-DuneRestartSchedule
                $previousCheck=[datetimeoffset]::MinValue
                if([datetimeoffset]::TryParse([string]$state.updateCheckedAt,[ref]$previousCheck) -and $previousCheck -gt [datetimeoffset]::Parse($checkedAt)){return}
                $state.updateAvailable=$available;$state.installedBuild=$installed;$state.latestBuild=$latest;$state.updateCheckedAt=$checkedAt
                Save-DuneRestartSchedule $state
            }|Out-Null
        }
        return $result
    }catch{
        return @{ok=$false;status=502;available=$false;checkedAt=$checkedAt;message=('Docker update check failed: '+$_.Exception.Message)}
    }
}

function Start-DuneDockerFuncomUpdate {
    param([bool]$AllowOnline=$false,[switch]$Recover,[switch]$WithTanks)
    if($Recover){return Invoke-DuneDockerManager -Request @{action='updates.recover'}}
    $version=Get-DuneDockerFuncomUpdateStatus -Persist
    if(-not $version.ok){return @{ok=$false;error=$version.message}}
    if([long]$version.latestBuild -lt [long]$version.installedBuild){return @{ok=$false;error='The public build is older than this installation. Automatic downgrade was blocked.'}}
    return Invoke-DuneDockerManager -Request @{action='updates.apply';expectedBuild=[string]$version.latestBuild;allowOnline=$AllowOnline;withTanks=[bool]$WithTanks}
}

function Get-DuneDockerContainers {
    $reply=Invoke-DuneDockerManager -Request @{action='status'}
    if(-not $reply.ok){return @{ok=$false;status=503;message='Docker observations are unavailable.'}}
    $metadata=$reply.data
    $entries=@($metadata.services)+@($metadata.connectionServices)
    if($metadata.database){$database=$metadata.database.Clone();$database.component='postgres';$database.desiredState=$metadata.desiredState;$entries+=@($database)}
    $pods=@(foreach($entry in $entries){
        if(-not $entry.component){continue}
        $phase=switch($entry.state){running{'Running'};restarting{'Starting'};created{'Stopped'};exited{'Stopped'};default{'Unknown'}}
        $ready=$entry.state -eq 'running'
        if($entry.component -match '^game-(\d+)$'){$ready=$ready -and $entry.gameReady -eq $true}
        elseif($entry.health){$ready=$ready -and $entry.health -eq 'healthy'}
        $desired=if($entry.desiredState){[string]$entry.desiredState}else{[string]$metadata.desiredState}
        $status=if($phase -eq 'Stopped' -and $desired -eq 'running'){'Unexpected stop'}elseif($entry.state -eq 'running' -and $entry.health -eq 'unhealthy'){'Unhealthy'}else{$phase}
        $map=if($entry.component -match '^game-(\d+)$'){$partition=[int]$Matches[1];@($metadata.plan.games | Where-Object {$_.partition -eq $partition}) | Select-Object -First 1}else{$null}
        @{backend='docker';namespace='docker';name=$(if($entry.name){[string]$entry.name}else{[string]$entry.component});component=[string]$entry.component;map=[string]$map.map;desiredState=$desired;
          ready=$(if($ready){'1/1'}else{'0/1'});status=$status;phase=$phase;restarts=$null;node='Docker host';ip='';
          startTime=$(if($entry.startedAt -gt 0){[DateTimeOffset]::FromUnixTimeSeconds([long]$entry.startedAt).ToString('o')}else{''})}
    })
    return @{ok=$true;pods=$pods;count=$pods.Count}
}

function Get-DuneDockerStatus {
    param([string]$SnapshotPath='/data/docker/status.json',[switch]$ForcePorts,[switch]$LifecycleOnly)
    $snapshot = @{ available=$false; stale=$true; error='Waiting for Docker observations.' }
    try {
        $snapshot=Get-Content -LiteralPath $SnapshotPath -Raw | ConvertFrom-Json -AsHashtable
        $snapshot.stale=([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()-[double]$snapshot.observedAt)-gt 30
    } catch { }
    $reply=Invoke-DuneDockerManager -Request @{action='status'}
    $metadata=if($reply.ok){$reply.data}else{$null}
    if($metadata -and [string]$metadata.installedBuild -match '^\d{1,18}$'){
        try {Sync-DuneFuncomInstalledBuild -InstalledBuild ([string]$metadata.installedBuild)|Out-Null} catch {}
    }
    $connected=[bool]$snapshot.available -and -not $snapshot.stale -and [bool]$reply.ok
    $hostState=@{exists=[bool]$snapshot.available;running=$connected;name='Docker Engine';state=$(if($connected){'Running'}else{'Unavailable'});ip=$metadata.profile.address;uptime=0;kind='docker'}
    # Retired Docker containers are diagnostic history, not current game pods.
    # Lifecycle controls use the complete manager catalogue separately.
    $playerCounts=Get-DuneDockerPlayerCounts -Metadata $metadata
    $games=@(foreach($service in @($metadata.services | Where-Object { $_.component -match '^game-[0-9]+$' -and ($_.state -in @('running','restarting') -or $_.desiredState -eq 'running') })) {
        $partition=[int]$service.component.Substring(5)
        $definition=@($metadata.plan.games | Where-Object { $_.partition -eq $partition }) | Select-Object -First 1
        $phase=Get-DuneDockerGamePhase -Service $service -Operation $metadata.operation
        $ready=if($service.ContainsKey('gameReady')){if($service.gameReady){'True'}else{'False'}}else{'Unknown'}
        $age=if($service.startedAt){Format-DuneKubeAge -Start ([DateTimeOffset]::FromUnixTimeSeconds([long]$service.startedAt).UtcDateTime)}else{''}
        $players=if($service.state -ne 'running'){'0'}elseif($service.gameServerId -and $playerCounts.ContainsKey([string]$service.gameServerId)){[string]$playerCounts[[string]$service.gameServerId]}elseif($service.ContainsKey('players') -and [int]$service.players -gt 0){[string]$service.players}else{'Unknown'}
        @{map=[string]$definition.map;phase=$phase;ready=$ready;players=$players;age=$age;desiredState=$service.desiredState}
    })
    $coreRunning=@($metadata.services | Where-Object { $_.component -notmatch '^game-[0-9]+$' -and $_.state-ne'running' }).Count-eq 0 -and @($metadata.services).Count-gt 0
    $queuesHealthy=@($metadata.connectionServices | Where-Object { $_.health-ne'healthy' }).Count-eq 0 -and @($metadata.connectionServices).Count-eq 2
    $expectedGames=@($games | Where-Object {$_.desiredState-eq'running'})
    $databaseReady=$metadata.database.state -eq 'running' -and $metadata.database.health -eq 'healthy'
    $databaseStatus=if(-not $metadata.database){'Not configured'}elseif($metadata.database.state -in @('created','exited')){'Stopped'}elseif($metadata.database.state -eq 'restarting'){'Starting'}elseif($databaseReady){'Ready'}elseif($metadata.database.state -eq 'running'){if($metadata.database.health){[string]$metadata.database.health}else{'Unknown'}}else{if($metadata.database.state){[string]$metadata.database.state}else{'Unknown'}}
    $allReady=$connected -and $coreRunning -and $queuesHealthy -and $databaseReady -and $expectedGames.Count-gt 0 -and @($expectedGames | Where-Object { $_.ready-ne'True' }).Count-eq 0
    $activeServices=@($metadata.services | Where-Object {$_.state -in @('running','restarting')}).Count -gt 0
    $state=if(-not $connected){'unknown'}elseif($metadata.operation.phase-eq'running'-and $metadata.operation.action-eq'services.stop'){'stopping'}elseif($metadata.desiredState-eq'stopped'){if($activeServices){'stopping'}else{'stopped'}}elseif($allReady){'running'}elseif($coreRunning){'starting'}else{'unknown'}
    if($state -in @('stopping','stopped')){
        foreach($game in $games){$game.phase=if($state -eq 'stopping'){'Stopping'}else{'Stopped'};$game.ready='False'}
    }
    $director=@($metadata.services | Where-Object { $_.component-eq'director' }) | Select-Object -First 1
    $gateway=@($metadata.services | Where-Object { $_.component-eq'gateway' }) | Select-Object -First 1
    $uptime=if($director.state-eq'running' -and $director.startedAt){Format-DuneKubeAge -Start ([DateTimeOffset]::FromUnixTimeSeconds([long]$director.startedAt).UtcDateTime)}else{''}
    $group=@{available=$connected;state=$state;name=$metadata.profile.name;title=$metadata.profile.name;gameServers=$games;
        reason=$(if(-not $connected){'Docker observations are unavailable or stale.'}else{$null});
        info=@{status=$(if($state -in @('stopping','stopped')){$state}elseif($allReady){'Ready'}else{$state});database=$databaseStatus;gateway=$(if($gateway.state-eq'running'){'Running'}else{[string]$gateway.state});director=$(if($director.state-eq'running'){'Running'}else{[string]$director.state});uptime=$uptime}}
    $ports=$null
    if($metadata.profile -and -not $LifecycleOnly){
        $required=@(@{Port=[int]$metadata.profile.gamePortBase;Protocol='UDP';Label='Game (first)'},
                    @{Port=([int]$metadata.profile.gamePortBase+33);Protocol='UDP';Label='Game (last)'},
                    @{Port=[int]$metadata.plan.ports.'rmq-game';Protocol='TCP';Label='RabbitMQ'})
        try {$ports=Get-DunePortStatus -Force:$ForcePorts -BattlegroupState $state -RequiredPorts $required} catch {}
        if($ports -and -not $ports.cached){
            # External observers can take longer than a map state transition.
            # Publish freshly collected lifecycle facts after the probe rather
            # than timestamping the older pre-probe snapshot as current.
            $fresh=Get-DuneDockerStatus -SnapshotPath $SnapshotPath -LifecycleOnly
            $fresh.ports=$ports
            return $fresh
        }
    }
    # Legacy screens consume vm as their managed-host availability field,
    # including fresh lifecycle checks outside useStatus. Supply the same
    # Docker host facts there; kind/backend identify Docker, and no VM probe runs.
    try {$schedule=Get-DuneRestartSchedule} catch {$schedule=@{}}
    return @{funcomUpdate=@{available=[bool]$schedule.updateAvailable;installedBuild=[string]$schedule.installedBuild;latestBuild=[string]$schedule.latestBuild;autoApply=[bool]$schedule.applyFuncomUpdates};hostingBackend='docker';host=$hostState;vm=$hostState;
             bg=$group;ports=$ports;serverName=[string]$metadata.profile.name;docker=$snapshot;ts=(Get-Date).ToString('o')}
}

# Used by existing maintenance workflows that require a completed stop before
# writing saved state. Ordinary UI start/stop controls remain asynchronous.
function Invoke-DuneDockerServiceLifecycle {
    param([ValidateSet('stop','start')][string]$Command,[int]$TimeoutSec=600)
    $reply=Invoke-DuneDockerManager -Request @{action="services.$Command"}
    if(-not $reply.ok){return @{ok=$false;error=[string]$reply.error}}
    $id=[string]$reply.data.operation.id
    if($id -notmatch '^[a-f0-9]{32}$'){return @{ok=$false;error='Docker lifecycle operation was not identified. Check server state before retrying.'}}
    $deadline=[DateTime]::UtcNow.AddSeconds($TimeoutSec)
    while([DateTime]::UtcNow -lt $deadline){
        $current=Invoke-DuneDockerManager -Request @{action='status'}
        if(-not $current.ok){return @{ok=$false;error='Docker lifecycle completion could not be verified.'}}
        $operation=$current.data.operation
        if($operation.id -ne $id -or $operation.phase -in @('failed','interrupted')){
            return @{ok=$false;error=$(if($operation.error){[string]$operation.error}else{'Docker lifecycle state changed. Check the server before retrying.'})}
        }
        if($operation.phase -eq 'completed'){
            $expected=if($Command -eq 'stop'){'stopped'}else{'running'}
            if($current.data.desiredState -ne $expected){return @{ok=$false;error='The requested Docker lifecycle state was not confirmed.'}}
            if($Command -eq 'stop' -and @($current.data.services | Where-Object {$_.component -match '^game-[0-9]+$' -and $_.state -notin @('exited','created','dead')}).Count){
                return @{ok=$false;error='A game process has not stopped. Saved-state changes were blocked.'}
            }
            return @{ok=$true;command=$Command;output="Docker battlegroup $Command completed.";operationId=$id}
        }
        Start-Sleep -Milliseconds 250
    }
    return @{ok=$false;error='Docker lifecycle operation is still pending. Check the server before retrying.'}
}
