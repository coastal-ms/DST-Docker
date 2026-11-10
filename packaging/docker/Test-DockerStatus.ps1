$ExpectedMapCount=2
$ErrorActionPreference = 'Stop'
. /opt/dst/app/server/lib/DockerManager.ps1
. /opt/dst/app/server/lib/Status.ps1
. /opt/dst/app/server/lib/Config.ps1
. /opt/dst/app/server/lib/Ports.ps1
$metadata=(Invoke-DuneDockerManager -Request @{action='status'}).data
$status=Get-DuneDockerStatus
if($status.hostingBackend -ne 'docker' -or -not $status.host.running) { throw 'Native Docker host observation failed.' }
if($status.vm.kind -ne 'docker' -or -not $status.vm.running -or $status.vm.name -ne 'Docker Engine') { throw 'Legacy managed-host fields did not identify the Docker Engine.' }
if(@($status.bg.gameServers).Count -ne $ExpectedMapCount) { throw 'Expected the initial owned test game maps.' }
if($status.bg.state -ne 'running' -or @($status.bg.gameServers | Where-Object { $_.ready -ne 'True' }).Count) { throw 'Fresh game-ready heartbeats were not reflected in the shared status contract.' }
if($status.serverName -ne $metadata.profile.name -or $status.host.ip -ne $metadata.profile.address) { throw 'Wrong owned test world was observed.' }
if(@($status.ports.results | Where-Object { $_.protocol -eq 'TCP' -and $_.port -eq $metadata.plan.ports.'rmq-game' }).Count -ne 1 -or $status.ports.publicIp -eq $metadata.profile.address) { throw 'Native TCP port/public address did not reach the shared UI status model.' }
@{ok=$true;hostingBackend=$status.hostingBackend;managedHostAlias=$status.vm.kind;state=$status.bg.state;games=$status.bg.gameServers;ports=$status.ports.results} | ConvertTo-Json -Depth 6
