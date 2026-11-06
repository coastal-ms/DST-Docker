function Invoke-DuneDockerManager {
    param([Parameter(Mandatory)][hashtable]$Request)
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = 'python3'
    [void]$start.ArgumentList.Add('/opt/dst/packaging/docker/manager-client.py')
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
    param([bool]$AllowOnline=$false,[switch]$Recover)
    if($Recover){return Invoke-DuneDockerManager -Request @{action='updates.recover'}}
    $version=Get-DuneDockerFuncomUpdateStatus -Persist
    if(-not $version.ok){return @{ok=$false;error=$version.message}}
    if([long]$version.latestBuild -lt [long]$version.installedBuild){return @{ok=$false;error='The public build is older than this installation. Automatic downgrade was blocked.'}}
    return Invoke-DuneDockerManager -Request @{action='updates.apply';expectedBuild=[string]$version.latestBuild;allowOnline=$AllowOnline}
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
    $connected=[bool]$snapshot.available -and -not $snapshot.stale -and [bool]$reply.ok
    $hostState=@{exists=[bool]$snapshot.available;running=$connected;name='Docker Engine';state=$(if($connected){'Running'}else{'Unavailable'});ip=$metadata.profile.address;uptime=0;kind='docker'}
    # Retired Docker containers are diagnostic history, not current game pods.
    # Lifecycle controls use the complete manager catalogue separately.
    $games=@(foreach($service in @($metadata.services | Where-Object { $_.component -match '^game-[0-9]+$' -and ($_.state -in @('running','restarting') -or $_.desiredState -eq 'running') })) {
        $partition=[int]$service.component.Substring(5)
        $definition=@($metadata.plan.games | Where-Object { $_.partition -eq $partition }) | Select-Object -First 1
        $phase=if($service.state-eq'running'){'Running'}elseif($service.state-eq'created'){'Pending'}elseif($service.state-eq'restarting'){'Starting'}else{'Failed'}
        $ready=if($service.ContainsKey('gameReady')){if($service.gameReady){'True'}else{'False'}}else{'Unknown'}
        if($phase-eq'Running' -and $ready-ne'True'){$phase='Starting'}
        if($metadata.operation.phase-eq'running' -and $metadata.operation.action-eq'maps.restart' -and $metadata.operation.partition-eq$partition -and $phase-eq'Failed'){$phase='Starting'}
        $age=if($service.startedAt){Format-DuneKubeAge -Start ([DateTimeOffset]::FromUnixTimeSeconds([long]$service.startedAt).UtcDateTime)}else{''}
        $players=if($service.ContainsKey('players')){[string]$service.players}elseif($service.state-eq'running'){'Unknown'}else{'0'}
        @{map=[string]$definition.map;phase=$phase;ready=$ready;players=$players;age=$age;desiredState=$service.desiredState}
    })
    $coreRunning=@($metadata.services | Where-Object { $_.component -notmatch '^game-[0-9]+$' -and $_.state-ne'running' }).Count-eq 0 -and @($metadata.services).Count-gt 0
    $queuesHealthy=@($metadata.connectionServices | Where-Object { $_.health-ne'healthy' }).Count-eq 0 -and @($metadata.connectionServices).Count-eq 2
    $expectedGames=@($games | Where-Object {$_.desiredState-eq'running'})
    $allReady=$connected -and $coreRunning -and $queuesHealthy -and $metadata.database.health-eq'healthy' -and $expectedGames.Count-gt 0 -and @($expectedGames | Where-Object { $_.ready-ne'True' }).Count-eq 0
    $state=if(-not $connected){'unknown'}elseif($metadata.operation.phase-eq'running'-and $metadata.operation.action-eq'services.stop'){'stopping'}elseif($metadata.desiredState-eq'stopped'){'stopped'}elseif($allReady){'running'}elseif($coreRunning){'starting'}else{'unknown'}
    $director=@($metadata.services | Where-Object { $_.component-eq'director' }) | Select-Object -First 1
    $gateway=@($metadata.services | Where-Object { $_.component-eq'gateway' }) | Select-Object -First 1
    $uptime=if($director.state-eq'running' -and $director.startedAt){Format-DuneKubeAge -Start ([DateTimeOffset]::FromUnixTimeSeconds([long]$director.startedAt).UtcDateTime)}else{''}
    $group=@{available=$connected;state=$state;name=$metadata.profile.name;title=$metadata.profile.name;gameServers=$games;
        reason=$(if(-not $connected){'Docker observations are unavailable or stale.'}else{$null});
        info=@{status=$(if($allReady){'Ready'}else{$state});database=$(if($metadata.database.health-eq'healthy'){'Ready'}else{[string]$metadata.database.health});gateway=$(if($gateway.state-eq'running'){'Running'}else{[string]$gateway.state});director=$(if($director.state-eq'running'){'Running'}else{[string]$director.state});uptime=$uptime}}
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
    return @{hostingBackend='docker';host=$hostState;vm=$hostState;
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
