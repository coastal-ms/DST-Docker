. /qualification-base.ps1 -InitializeOnly
foreach($library in @('Config.ps1','GameConfig.ps1','BaseBackupGuard.ps1','DockerSettings.ps1','DockerMaps.ps1')){
    . (Join-Path /opt/dst/app/server/lib $library)
}
. /opt/dst/app/lib/K8s.ps1
function Invoke-WithDuneLock {param($Name,$Script);& $Script}
function Invoke-FixtureSettings([hashtable]$Request){
    # This container has only the isolated settings socket; /control is absent.
    Invoke-DuneDockerSettingsReader -Request $Request
}
function Invoke-DuneDockerManager {
    param($Request)
    $data=switch($Request.action){
        'settings.backup' {Invoke-FixtureSettings @{action='backups.create';files=$Request.files};break}
        'settings.write' {
            $payload=@{};foreach($key in $Request.Keys){$payload[$key]=$Request[$key]};$payload.action='write'
            Invoke-FixtureSettings $payload;break
        }
        'status' {@{projectId=('f'*32);profile=@{name='Isolated settings fixture'};
            plan=@{games=@(@{partition=8;map='DeepDesert_1';gamePort=28784})};
            desiredState='running';services=@(@{component='game-1';state='running';gameReady=$true},@{component='game-8';state='running';gameReady=$true})};break}
        default {throw 'This isolated qualification cannot dispatch production management actions.'}
    }
    return @{ok=$true;data=$data}
}

$gameBefore=Read-DuneDockerSettingsFile -File game
$engineBefore=Read-DuneDockerSettingsFile -File engine
try {
    $time=Invoke-DuneTwilightLockStage -Ip docker -Candidate '18.0'
    if(-not $time.ok -or -not $time.restartRequired){throw 'Time-of-day staging failed.'}
    $config=Get-DuneTwilightLockConfig -Ip docker
    if($config.current.candidate -ne '18.0'){throw 'Time-of-day candidate did not read back.'}
    $null=Invoke-DuneTwilightLockRestore -Ip docker
    $after=Read-DuneDockerSettingsFile -File game
    if($after.raw -notmatch 'ManualSetting=preserved'){throw 'Time-of-day restore lost a manual setting.'}
    $checks.Add('Native authoritative time-of-day staging and restore preserve manual INI content without a restart')

    $pvp=Set-DuneDeepDesertPvp -Enabled $true -PartitionIds @(8)
    if(-not $pvp.ok -or -not $pvp.pendingApply -or @($pvp.selectedPartitionIds) -notcontains 8){throw ('Deep Desert PvP staging failed: '+($pvp|ConvertTo-Json -Compress -Depth 4))}
    $invalid=Set-DuneDeepDesertPvp -Enabled $true -PartitionIds @(999)
    if($invalid.ok -or $invalid.status -ne 400){throw 'An unknown Deep Desert partition was accepted.'}
    $cleared=Set-DuneDeepDesertPvp -Enabled $false -PartitionIds @()
    if(-not $cleared.ok -or $cleared.enabled){throw 'Deep Desert PvP did not clear.'}
    $checks.Add('Deep Desert PvP uses actual restored database partition identity and rejects unknown instances')

    $guardBefore=Get-DuneBaseBackupGuardState -Ip docker
    if(-not $guardBefore.ok -or -not $guardBefore.functionFound){throw 'The restored official base-backup cleanup function was not found.'}
    try {
        $removed=Invoke-DuneBaseBackupGuardRevert -Ip docker
        if(-not $removed.ok){throw ('Initial guard restore failed: '+$removed.message)}
        $applied=Invoke-DuneBaseBackupGuardApply -Ip docker
        if(-not $applied.ok -or -not $applied.applied){throw ('Native base backup guard apply failed: '+$applied.message)}
        $again=Invoke-DuneBaseBackupGuardApply -Ip docker
        if(-not $again.ok -or $again.changed){throw 'Repeated guard apply was not idempotent.'}
        $reverted=Invoke-DuneBaseBackupGuardRevert -Ip docker
        if(-not $reverted.ok -or $reverted.applied){throw ('Native guard restore failed: '+$reverted.message)}
        $checks.Add('Restored-copy base-backup safeguard applies, reads back, repeats idempotently and reverts using the unprivileged dune role')
    } finally {
        $out=Invoke-DuneSqlRawStdin -Ip docker -Sql $guardBefore.definition
        if(Test-DunePsqlError -Output $out){throw 'The original qualification function could not be restored.'}
        $restored=Get-DuneBaseBackupGuardState -Ip docker
        if($restored.definition -cne $guardBefore.definition){throw 'Restored qualification function differs from the original.'}
    }
} finally {
    foreach($entry in @(@{file='game';before=$gameBefore},@{file='engine';before=$engineBefore})){
        $current=Read-DuneDockerSettingsFile -File $entry.file
        $null=Write-DuneDockerSettingsFile -File $entry.file -Raw $entry.before.raw -Revision $current.revision -ExpectedExists $current.fileExists
    }
}
@{ok=$true;checks=$checks;isolatedSettings=$true;database=$settings.database;role='dune';noProductionManagerSocket=$true}|ConvertTo-Json -Depth 5
