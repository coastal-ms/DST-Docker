. /qualification-base.ps1 -InitializeOnly
$controller=[long]$player.controller_id
function Read-One([string]$Sql){
    $result=Invoke-DuneSqlQuery -Ip docker -ReadOnly $true -Sql $Sql -MaxRows 1
    Assert-Ok $result 'Readback'
    return (ConvertTo-DuneRowMaps -Result $result)[0]
}
$track=[string](Read-One 'SELECT unnest(enum_range(NULL::dune.specializationtracktype))::text AS track LIMIT 1;').track
$max=Invoke-DunePlayerGrantMaxSpec -Ip docker -ControllerId $controller -TrackType $track
Assert-Ok $max 'Max specialization'
$safeTrack=ConvertTo-DuneSqlString $track
$row=Read-One "SELECT level::text AS level FROM dune.specialization_tracks WHERE player_id=$controller AND track_type::text='$safeTrack';"
if([double]$row.level -ne 100){throw 'Max specialization did not reach 100.'}
Assert-Ok (Invoke-DunePlayerResetSpec -Ip docker -ControllerId $controller -TrackType $track) 'Reset one specialization'
$row=Read-One "SELECT count(*)::text AS count FROM dune.specialization_tracks WHERE player_id=$controller AND track_type::text='$safeTrack';"
if([long]$row.count -ne 0){throw 'Reset track remained in the database.'}
$checks.Add('Existing max and single-track reset produce the expected stored specialization rows')

Assert-Ok (Invoke-DunePlayerGrantAllKeystones -Ip docker -ControllerId $controller) 'Grant keystones'
$row=Read-One "SELECT count(*)::text AS count FROM dune.purchased_specialization_keystones WHERE player_id=$controller;"
if([long]$row.count -lt 1){throw 'Keystone grant did not store purchases.'}
Assert-Ok (Invoke-DunePlayerPreparePatternUpgrading -Ip docker -ControllerId $controller) 'Prepare Pattern Upgrading'
$row=Read-One "SELECT count(*)::text AS count FROM dune.purchased_specialization_keystones WHERE player_id=$controller AND keystone_id=$script:DunePatternUpgradingKeystoneId;"
if([long]$row.count -ne 0){throw 'Pattern Upgrading remained claimed.'}
Assert-Ok (Invoke-DunePlayerResetAllKeystones -Ip docker -ControllerId $controller) 'Reset keystones'
$row=Read-One "SELECT count(*)::text AS count FROM dune.purchased_specialization_keystones WHERE player_id=$controller;"
if([long]$row.count -ne 0){throw 'Keystone reset left purchases.'}
$checks.Add('Keystone grant/reset and manual Pattern Upgrading purchase preparation reuse the existing transaction logic')

Assert-Ok (Invoke-DunePlayerApplySpecLevel -Ip docker -ControllerId $controller -TrackType $track -Level 12) 'Track fixture'
Assert-Ok (Invoke-DunePlayerGrantAllKeystones -Ip docker -ControllerId $controller) 'Keystone fixture'
Assert-Ok (Invoke-DunePlayerResetAllSpecs -Ip docker -ControllerId $controller) 'Reset all specializations'
$row=Read-One "SELECT (SELECT count(*) FROM dune.specialization_tracks WHERE player_id=$controller)::text AS tracks,(SELECT count(*) FROM dune.purchased_specialization_keystones WHERE player_id=$controller)::text AS keystones;"
if([long]$row.tracks -ne 0 -or [long]$row.keystones -ne 0){throw 'Full specialization reset left tracks or purchases.'}
$checks.Add('Full specialization reset clears tracks and keystones together')

$defaults=Get-DuneItemStatDefaultsSql -Block FWeaponItemStats
$template=[string](Read-One "SELECT key AS template FROM jsonb_each($defaults) ORDER BY key LIMIT 1;").template
if(-not $template){throw 'No authoritative ranged weapon defaults were found.'}
$item=Invoke-DunePlayerGiveItem -Ip docker -PawnId $pawn -Template $template -Qty 1 -Quality 0
Assert-Ok $item 'Ranged weapon fixture'
$itemId=[long]$item.item_id
$row=Read-One "SELECT COALESCE(stats #>> '{FWeaponItemStats,1,CurrentAmmo}','0') AS ammo FROM dune.items WHERE id=$itemId;"
$before=[long]$row.ammo
Assert-Ok (Invoke-DunePlayerSetWeaponAmmo -Ip docker -PawnId $pawn -ItemId $itemId -Ammo 17 -ExpectedAmmo $before) 'Weapon ammo edit'
$row=Read-One "SELECT stats #>> '{FWeaponItemStats,1,CurrentAmmo}' AS ammo FROM dune.items WHERE id=$itemId;"
if([long]$row.ammo -ne 17){throw 'Loaded ammo did not match readback.'}
$stale=Invoke-DunePlayerSetWeaponAmmo -Ip docker -PawnId $pawn -ItemId $itemId -Ammo 18 -ExpectedAmmo 99999
if($stale.ok){throw 'Stale ammo edit succeeded.'}
Assert-Ok (Invoke-DunePlayerDeleteItem -Ip docker -ItemId $itemId -ExpectedStackSize 1) 'Remove ranged fixture'
$checks.Add('Loaded ammo editor preserves offline identity and expected-value guards')
@{ok=$true;checks=$checks.ToArray();liveWorldMutated=$false} | ConvertTo-Json -Depth 4
