$ErrorActionPreference = 'Stop'
$settings = Get-Content /data/config/DuneServer/docker-database.json -Raw | ConvertFrom-Json
if ($settings.host -ne '127.0.0.1' -or $settings.port -ne 18932 -or $settings.database -notmatch '^dst_qualify_[a-f0-9]{24}$' -or -not $settings.allowWrites) {
    throw 'Character mutation qualification is restricted to a generated restored-copy database.'
}
$env:DST_HOSTING_BACKEND = 'docker'
$script:AppDir = '/opt/dst/app'
foreach ($library in @('app/lib/Db-Postgres.ps1','app/server/lib/DockerDatabase.ps1','app/server/lib/Database.ps1',
    'app/server/lib/Gameplay.ps1','app/server/lib/GameplayPlayers.ps1','app/server/lib/PlayersWrites.ps1',
    'app/server/lib/PlayersRead.ps1','app/server/lib/PlayersAdmin.ps1','app/server/lib/PlayerGuard.ps1',
    'app/server/lib/SoloMode.ps1','app/server/lib/Codex.ps1')) {
    . (Join-Path /opt/dst $library)
}
function Assert-Result($Result,[string]$Action) {
    if (-not $Result.ok) { throw "$Action failed: $($Result.error) $($Result.reason)" }
}
$identity=Invoke-DuneSqlQuery -Ip docker -Sql 'SELECT current_database() AS database, current_user AS role' -ReadOnly $true
Assert-Result $identity 'Connection identity'
$identityRow=@(ConvertTo-DuneRowMaps -Result $identity)[0]
if ($identityRow.database -ne $settings.database -or $identityRow.role -ne 'dune') { throw 'Unexpected qualification database identity.' }
$players=Get-DunePlayersLive -Ip docker
Assert-Result $players 'Restored player list'
if (@($players.players).Count -ne 1) { throw 'This initial qualification expects one restored test character.' }
$player=$players.players[0]
$pawn=[long]$player.id; $account=[long]$player.account_id; $controller=[long]$player.controller_id
$checks=[Collections.Generic.List[string]]::new()
$guard=Test-DunePlayerOffline -Ip docker -PawnId $pawn -RequireVerifiedStatus
Assert-Result $guard 'Verified offline guard'
$checks.Add('Restored character resolves through the unchanged Players query and strict offline guard')

foreach ($status in @('Online','LoggingOut')) {
    try {
        $changed=Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "UPDATE dune.player_state SET online_status='$status' WHERE player_pawn_id=$pawn"
        Assert-Result $changed 'Clone status fixture'
        $blocked=Test-DunePlayerOffline -Ip docker -PawnId $pawn -RequireVerifiedStatus
        if ($blocked.ok) { throw "Existing offline guard allowed $status." }
    } finally {
        $restored=Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "UPDATE dune.player_state SET online_status='Offline' WHERE player_pawn_id=$pawn"
        Assert-Result $restored 'Restore clone offline state'
    }
}
$checks.Add('Existing guard rejects Online and LoggingOut before character edits')

$stats=Get-DunePlayerStatsLive -Ip docker -PawnId $pawn
Assert-Result $stats 'Character statistics'
if (-not $stats.stats -or $stats.stats.account_id -ne $account) { throw 'Restored statistics do not match the selected character.' }
$detail=Get-DunePlayerDetailLive -Ip docker -PawnId $pawn -ControllerId $controller
Assert-Result $detail 'Inventory and specialization detail'
$checks.Add('Populated character statistics, inventory and specialization reads use native transport')

$originalName=[string]$player.name
try {
    $name="Docker fixture, 生命 ' quoted"
    $renamed=Invoke-DunePlayerRename -Ip docker -AccountId $account -Name $name
    Assert-Result $renamed 'Clone rename'
    $readback=Get-DunePlayersLive -Ip docker
    Assert-Result $readback 'Renamed clone readback'
    if ($readback.players[0].name -cne $name) { throw 'Quoted Unicode character name did not round-trip.' }
} finally {
    $renamed=Invoke-DunePlayerRename -Ip docker -AccountId $account -Name $originalName
    Assert-Result $renamed 'Restore clone name'
}
$checks.Add('Existing rename procedure preserves quoted Unicode and restores its original value')

$balance=[long]$stats.stats.solaris
$credit=Invoke-DunePlayerGiveSolari -Ip docker -ControllerId $controller -Amount 1234
Assert-Result $credit 'Clone currency grant'
$readback=Get-DunePlayerStatsLive -Ip docker -PawnId $pawn
Assert-Result $readback 'Currency readback'
if ([long]$readback.stats.solaris -ne $balance+1234) { throw 'Currency grant did not match its readback.' }
$debit=Invoke-DunePlayerGiveSolari -Ip docker -ControllerId $controller -Amount -1234
Assert-Result $debit 'Restore clone currency'
$checks.Add('Existing Solari stored procedure and statistics agree on native grant/debit results')

$quest=Invoke-DunePlayerCompleteJourneyNode -Ip docker -AccountId $account -NodeId 'DA_MQ_FindTheFremen'
Assert-Result $quest 'Find the Fremen completion on restored copy'
$flags=Invoke-DuneSqlQuery -Ip docker -ReadOnly $true -Sql @"
SELECT fe.components #>> '{FSpiceAddictionComponent,1,SystemStatus}' AS system,
       fe.components #>> '{FSpiceAddictionComponent,1,SpiceVisionEnabledStatus}' AS vision
FROM dune.actor_fgl_entities afe JOIN dune.fgl_entities fe ON fe.entity_id=afe.entity_id
WHERE afe.actor_id=$pawn AND afe.slot_name='DuneCharacter'
"@
Assert-Result $flags 'Prescience flag readback'
$flagRow=@(ConvertTo-DuneRowMaps -Result $flags)[0]
if ($flagRow.system -ne 'FullyEnabled' -or $flagRow.vision -ne 'FullyEnabled') { throw 'Find the Fremen did not enable both required flags.' }
$tags=Get-DunePlayerTagsLive -Ip docker -AccountId $account
Assert-Result $tags 'Journey reward tag readback'
if ('Journey.RewardsUnblocked' -notin $tags.tags) { throw 'Journey reward-unblock tag is missing.' }
$again=Invoke-DuneGrantSpiceVision -Ip docker -AccountId $account
Assert-Result $again 'Idempotent Prescience grant'
if ($again.applied) { throw 'A repeated Prescience grant rewrote already-enabled flags.' }
$checks.Add('Unchanged Find the Fremen completion applies both FullyEnabled flags and Journey.RewardsUnblocked; repeat grant is idempotent')

@{ok=$true;scope='Generated restored-copy database only; live character is untouched';checks=@($checks)} | ConvertTo-Json -Depth 5
