$ErrorActionPreference='Stop'
. /opt/dst/app/server/lib/DockerManager.ps1
. /opt/dst/app/server/lib/DockerMaps.ps1
. /opt/dst/app/server/lib/Status.ps1
$script:metadata=@{
    desiredState='running';profile=@{name='Fixture';address='127.0.0.1';gamePortBase=28777}
    database=@{health='healthy'};connectionServices=@(@{health='healthy'},@{health='healthy'})
    plan=@{ports=@{'rmq-game'=29779};games=@(@{partition=1;map='Survival_1'},@{partition=2;map='Overmap'},@{partition=8;map='DeepDesert_1'})}
    services=@(@{component='director';state='running';startedAt=([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()-600)},
        @{component='gateway';state='running'},@{component='text-router';state='running'},
        @{component='game-1';state='running';desiredState='running';gameReady=$true;players=2},
        @{component='game-2';state='running';desiredState='running';gameReady=$true;players=0},
        @{component='game-8';state='exited';desiredState='stopped'})
}
function Invoke-DuneDockerManager {param($Request) return @{ok=$true;data=$script:metadata}}
function Get-DunePortStatus {param($Force,$BattlegroupState,$RequiredPorts) return @{mode='builtin';showUdp=$false;results=@($RequiredPorts | Where-Object Protocol -eq 'TCP')}}
$snapshot='/tmp/dst-status-lifecycle.json'
try {
    @{available=$true;observedAt=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()} | ConvertTo-Json | Set-Content $snapshot
    $status=Get-DuneDockerStatus -SnapshotPath $snapshot
    if($status.vm.kind -ne 'docker' -or -not $status.vm.running -or $status.vm.ip -ne $status.host.ip){
        throw 'Fresh lifecycle consumers did not receive the Docker managed-host compatibility facts.'
    }
    if($status.bg.state-ne'running' -or $status.bg.gameServers[0].players-ne'2' -or $status.bg.info.uptime-ne'10m'){
        throw 'Ready login maps and a cold optional map did not produce accurate running status.'
    }
    if(@($status.bg.gameServers).Count -ne 2 -or @($status.bg.gameServers | Where-Object map -eq 'DeepDesert_1').Count){
        throw 'A shutdown optional map was included in the current game-server table.'
    }
    $coldMap=Get-DuneDockerMapState -Key deepdesert
    if(-not $coldMap.present -or $coldMap.activeInstances -ne 0){throw 'A shutdown map disappeared from lifecycle controls.'}
    if($status.ports.mode -ne 'builtin' -or $status.ports.showUdp -or $status.ports.results[0].Port -ne 29779){throw 'Overview did not use shared port checks with the owned world port.'}
    $script:metadata.services[5].state='created'
    if(@((Get-DuneDockerStatus -SnapshotPath $snapshot).bg.gameServers).Count -ne 2){throw 'A prepared but unstarted optional map appeared as a current pod.'}
    $script:metadata.services[5].state='exited'
    $script:metadata.services[3].gameServerId='0Iz_yEv_NUmWIwxmG8muig'
    $script:mapPlayers=@{count=2;ids=@('11','12')}
    function _Get-DuneMapPlayersOnline {param($Ip,$ServerGuids) return $script:mapPlayers}
    $map=Get-DuneDockerMapState -Key survival
    if($map.playersOnline -ne 2 -or $map.playerIds.Count -ne 2){throw 'Native map did not reuse player identity lookup for the live server.'}
    $script:metadata.services[3].players=3
    $map=Get-DuneDockerMapState -Key survival
    if($map.playersOnline -ne 3 -or -not $map.playersError){throw 'Heartbeat occupancy was lowered while identities were still catching up.'}
    $script:mapPlayers=@{count=-1;ids=@();error='Fixture database unavailable'}
    $map=Get-DuneDockerMapState -Key survival
    if($null -ne $map.playersOnline -or -not $map.playersError){throw 'Failed map identity lookup was reported as empty.'}
    $script:metadata.services[3].Remove('gameServerId')
    $script:metadata.services[3].gameReady=$false
    function Get-DunePortStatus {
        param($Force,$BattlegroupState,$RequiredPorts)
        $script:metadata.services[3].gameReady=$true
        return @{mode='builtin';showUdp=$false;cached=$false;results=@($RequiredPorts | Where-Object Protocol -eq 'TCP')}
    }
    $status=Get-DuneDockerStatus -SnapshotPath $snapshot
    if($status.bg.gameServers[0].ready -ne 'True'){throw 'A completed external probe published the earlier map-readiness snapshot.'}
    function Get-DunePortStatus {param($Force,$BattlegroupState,$RequiredPorts) return @{mode='builtin';showUdp=$false;cached=$true;results=@($RequiredPorts | Where-Object Protocol -eq 'TCP')}}
    $script:metadata.services[3].Remove('gameReady');$script:metadata.services[3].Remove('players')
    $status=Get-DuneDockerStatus -SnapshotPath $snapshot
    if($status.bg.state-ne'starting' -or $status.bg.gameServers[0].phase-ne'Starting' -or $status.bg.gameServers[0].players-ne'Unknown'){
        throw 'Missing readiness/occupancy was presented as ready or empty.'
    }
    $script:metadata.services[5].desiredState='running'
    $map=Get-DuneDockerMapState -Key deepdesert
    if($map.targetInstances -ne 1 -or $map.activeInstances -ne 0 -or $map.running){throw 'Desired startup was confused with an actual running map.'}
    @{available=$true;observedAt=([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()-90)} | ConvertTo-Json | Set-Content $snapshot
    $status=Get-DuneDockerStatus -SnapshotPath $snapshot
    if($status.bg.state-ne'unknown' -or $status.host.running -or -not $status.bg.reason){throw 'Stale Docker observations were presented as a fresh startup signal.'}
    $script:metadata.desiredState='stopped'
    foreach($service in $script:metadata.services){$service.state='exited';$service.desiredState='stopped'}
    if(@((Get-DuneDockerStatus -SnapshotPath $snapshot).bg.gameServers).Count){throw 'Stopped world retained rows in the current pod table.'}
    @{ok=$true;checks=@('Ready maps and occupied counts','Shutdown maps absent from Overview but retained in lifecycle controls','Unstarted optional map absent from current pods','Shared checker receives configured native TCP port','Cold optional map does not poison readiness','Missing heartbeat is Starting with unknown occupancy','Desired replicas remain separate from running instances','Stale observation is Unknown','Native director uptime uses shared duration formatting','Stopped world has no current map pods','Native map server identity resolves player IDs','Missing identities or failed SQL cannot lower known occupancy','Lifecycle facts are resampled after an external port probe')} | ConvertTo-Json -Depth 3
} finally {Remove-Item -LiteralPath $snapshot -ErrorAction SilentlyContinue}
