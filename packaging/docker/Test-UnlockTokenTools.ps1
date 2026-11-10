. /qualification-base.ps1 -InitializeOnly
. /opt/dst/app/server/lib/Rmq.ps1
$script:packets=[Collections.Generic.List[object]]::new()
function Invoke-DuneRmqAddItemsToInventoryBatch {
    param([string]$FlsId,[string[]]$ItemNames,[int]$SpacingMilliseconds)
    $script:packets.Add(@{fls=$FlsId;items=$ItemNames;spacing=$SpacingMilliseconds})
    return @{ok=$true;total=$ItemNames.Count;message='Qualification capture only.'}
}
foreach($kind in @('armor','weapon','vehicle','dyes')){
    $result=Invoke-DunePlayerGrantSkins -Ip docker -PawnId $pawn -AccountId $account -Kind $kind
    if($result.ok){throw 'Offline token grant was accepted.'}
}
if($script:packets.Count){throw 'Offline token grant published a message.'}
$checks.Add('Skin grants retain the exact-online guard before token delivery')
try {
    Assert-Ok (Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "UPDATE dune.player_state SET online_status='Online' WHERE player_pawn_id=$pawn;") 'Online clone fixture'
    $mismatch=Invoke-DunePlayerGrantSkins -Ip docker -PawnId $pawn -AccountId ($account+1) -Kind armor
    if($mismatch.ok -or $script:packets.Count){throw 'Mismatched character identity reached delivery.'}
    foreach($kind in @('building-sets','armor','weapon','vehicle','dyes')){
        $before=$script:packets.Count
        $result=Invoke-DunePlayerGrantUnlockTokens -Ip docker -PawnId $pawn -AccountId $account -Kind $kind
        Assert-Ok $result "$kind token request"
        if($result.requested -lt 1 -or $script:packets.Count -ne $before+1){throw "$kind did not resolve its catalog/missing token batch."}
        $packet=$script:packets[$before]
        if($packet.items.Count -ne $result.submitted -or $packet.spacing -ne 200 -or [string]::IsNullOrWhiteSpace($packet.fls)){
            throw "$kind token delivery changed its existing pacing, identity or count."
        }
    }
    $checks.Add('Building sets and all four skin groups resolve installed catalogs, real ownership and paced missing-token requests')
    $result=Invoke-DunePlayerGrantHouseSwatches -Ip docker -PawnId $pawn -AccountId $account -Kind placeables
    Assert-Ok $result 'House Swatches'
    if($result.requested -lt 1){throw 'House Swatch catalog did not resolve missing tokens.'}
    $checks.Add('House Swatch request reuses the existing catalog and live token workflow')
} finally {
    Assert-Ok (Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "UPDATE dune.player_state SET online_status='Offline' WHERE player_pawn_id=$pawn;") 'Restore offline clone'
}
@{ok=$true;checks=$checks.ToArray();capturedBatches=$script:packets.Count;liveWorldMutated=$false;actualTokenDelivery=$false} | ConvertTo-Json -Depth 4
