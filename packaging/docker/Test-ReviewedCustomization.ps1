. /qualification-base.ps1 -InitializeOnly
. /opt/dst/app/server/lib/SoloCosmetics.ps1
$controller=[long]$player.controller_id
foreach($selection in @('ObservedCharacterSwatches','ObservedGearAppearances','ObservedSchematicRecipes')){
    $sql=Get-DuneReviewedCustomizationSql -PawnId $pawn -ControllerId $controller -AccountId $account -CustomizationId $selection
    $write=Invoke-DuneSqlQuery -Ip docker -Sql $sql -ReadOnly $false -MaxRows 1 -TimeoutSec 120 -Bulk
    Assert-Ok $write "$selection native transaction"
    $rows=ConvertTo-DuneRowMaps -Result $write
    if($rows.Count -ne 1 -or -not $rows[0].ContainsKey('added')){throw 'Reviewed grant lost its transaction result.'}
    $status=Invoke-DuneSqlQuery -Ip docker -Sql (Get-DuneReviewedGrantStatusSql $pawn $controller $account $selection) -ReadOnly $true -MaxRows 1 -Bulk
    Assert-Ok $status "$selection readback"
    $rows=ConvertTo-DuneRowMaps -Result $status
    if($rows.Count -ne 1 -or [int]$rows[0].total -lt 1 -or [int]$rows[0].owned -ne [int]$rows[0].total){throw 'Reviewed grant ownership does not match its catalog.'}
    $again=Invoke-DuneSqlQuery -Ip docker -Sql $sql -ReadOnly $false -MaxRows 1 -TimeoutSec 120 -Bulk
    Assert-Ok $again "$selection idempotent repeat"
    if([int](ConvertTo-DuneRowMaps -Result $again)[0].added -ne 0){throw 'Reviewed grant duplicated entries.'}
    $checks.Add("$selection preserves the shared exact catalog, transaction result, ownership counts and idempotence")
}
try {
    Assert-Ok (Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "UPDATE dune.player_state SET online_status='Online' WHERE player_pawn_id=$pawn;") 'Online clone fixture'
    $blocked=Invoke-DuneSqlQuery -Ip docker -Sql (Get-DuneReviewedCustomizationSql $pawn $controller $account 'ObservedCharacterSwatches') -ReadOnly $false -MaxRows 1 -Bulk
    if($blocked.ok){throw 'Reviewed SQL grant bypassed its transaction-level offline guard.'}
} finally {
    Assert-Ok (Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "UPDATE dune.player_state SET online_status='Offline' WHERE player_pawn_id=$pawn;") 'Restore offline clone'
}
$checks.Add('Reviewed grant keeps the transaction-level offline identity guard')
@{ok=$true;checks=$checks.ToArray();liveWorldMutated=$false} | ConvertTo-Json -Depth 4
