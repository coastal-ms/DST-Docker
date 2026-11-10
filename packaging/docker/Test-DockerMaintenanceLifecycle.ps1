$ErrorActionPreference='Stop'
$env:DST_HOSTING_BACKEND='docker'
. /opt/dst/app/server/lib/DockerManager.ps1
. /opt/dst/app/server/lib/PlayersAdmin.ps1
$script:id='a'*32
$script:state=@{operation=@{id=$script:id;phase='completed'};desiredState='stopped';services=@(@{component='game-1';state='exited'})}
$script:requests=[Collections.Generic.List[string]]::new()
function Invoke-DuneDockerManager {
    param([hashtable]$Request)
    $script:requests.Add([string]$Request.action)
    return @{ok=$true;data=$script:state}
}
$checks=[Collections.Generic.List[string]]::new()
$stop=Invoke-DuneBaseWaterBgCommand -Ip docker -Command stop
if(-not $stop.ok -or $script:requests[0] -ne 'services.stop'){throw 'Existing maintenance stop did not use the native lifecycle adapter.'}
$script:state.desiredState='running';$script:state.services[0].state='running'
$start=Invoke-DuneBaseWaterBgCommand -Ip docker -Command start
if(-not $start.ok -or $script:requests[2] -ne 'services.start'){throw 'Existing maintenance start did not use the native lifecycle adapter.'}
$checks.Add('Existing stop/start maintenance calls use the completed native operation')
$script:state.desiredState='stopped'
if((Invoke-DuneBaseWaterBgCommand -Ip docker -Command stop).ok){throw 'A completed journal allowed writes while a game process was still running.'}
$script:state.services[0].state='unknown'
if((Invoke-DuneBaseWaterBgCommand -Ip docker -Command stop).ok){throw 'Unknown process state was accepted as a completed stop.'}
$checks.Add('Running and unknown game processes block saved-state writes after stop')
$script:state.services[0].state='exited';$script:state.operation.phase='failed';$script:state.operation.error='Fixture failure'
if((Invoke-DuneBaseWaterBgCommand -Ip docker -Command stop).ok){throw 'Failed stop was accepted.'}
$checks.Add('Failed lifecycle operation remains a failure')
$script:state.operation.phase='running'
if((Invoke-DuneDockerServiceLifecycle -Command stop -TimeoutSec 0).ok){throw 'Pending stop was accepted.'}
$checks.Add('Pending operation cannot authorize saved-state writes')
@{ok=$true;checks=$checks.ToArray();realServicesChanged=$false} | ConvertTo-Json -Depth 4
