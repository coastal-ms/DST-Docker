. /qualification-base.ps1 -InitializeOnly
$controller=[long]$player.controller_id
function Read-One([string]$Sql){
    $result=Invoke-DuneSqlQuery -Ip docker -ReadOnly $true -Sql $Sql -MaxRows 1
    Assert-Ok $result 'Readback'
    return @(ConvertTo-DuneRowMaps -Result $result)[0]
}
$item=Invoke-DunePlayerGiveItem -Ip docker -PawnId $pawn -Template 'CopperBar' -Qty 2 -Quality 0
Assert-Ok $item 'Stack fixture'
$itemId=[long]$item.item_id
$stack=Invoke-DunePlayerSetItemStack -Ip docker -ItemId $itemId -StackSize 9
Assert-Ok $stack 'Stack editor'
if([long](Read-One "SELECT stack_size::text AS count FROM dune.items WHERE id=$itemId;").count -ne 9){throw 'Stack size readback differs.'}
$stale=Invoke-DunePlayerDeleteItem -Ip docker -ItemId $itemId -ExpectedStackSize 999999
if($stale.ok){throw 'Delete ignored the expected quantity guard.'}
$deleted=Invoke-DunePlayerDeleteItem -Ip docker -ItemId $itemId -ExpectedStackSize 9
Assert-Ok $deleted 'Delete item'
if([long](Read-One "SELECT count(*)::text AS count FROM dune.items WHERE id=$itemId;").count -ne 0){throw 'Item remained after deletion.'}
$checks.Add('Stack editor and item deletion preserve expected-quantity guards and verify stored rows')

$item=Invoke-DunePlayerGiveItem -Ip docker -PawnId $pawn -Template 'ScrapMetalKnife' -Qty 1 -Quality 0
Assert-Ok $item 'Durability fixture';$itemId=[long]$item.item_id
$edited=Invoke-DunePlayerSetItemDurability -Ip docker -ItemId $itemId -Max 100 -Current 35 -Decayed 80
Assert-Ok $edited 'Durability editor'
$values=Read-One "SELECT stats #>> '{FItemStackAndDurabilityStats,1,CurrentDurability}' AS current,stats #>> '{FItemStackAndDurabilityStats,1,DecayedMaxDurability}' AS decayed FROM dune.items WHERE id=$itemId;"
if([double]$values.current -ne 35 -or [double]$values.decayed -ne 80){throw 'Durability values did not round-trip.'}
$repair=Invoke-DunePlayerRepairItem -Ip docker -ItemId $itemId
Assert-Ok $repair 'Per-item repair'
$values=Read-One "SELECT stats #>> '{FItemStackAndDurabilityStats,1,CurrentDurability}' AS current FROM dune.items WHERE id=$itemId;"
if([double]$values.current -ne 100){throw 'Repair did not reach factory durability.'}
$checks.Add('Per-item durability edits and repair match exact native readback')

$item=Invoke-DunePlayerGiveItem -Ip docker -PawnId $pawn -Template 'Literjon' -Qty 1 -Quality 0
Assert-Ok $item 'Water editor fixture';$itemId=[long]$item.item_id
$water=Invoke-DunePlayerSetItemWater -Ip docker -ItemId $itemId -Amount 75.5
Assert-Ok $water 'Water editor'
$values=Read-One "SELECT stats #>> '{FFillableItemStats,1,CurrentAmount}' AS amount FROM dune.items WHERE id=$itemId;"
if([double]$values.amount -ne 75.5){throw 'Fractional water amount did not round-trip.'}
$checks.Add('Per-item water editor preserves fractional amounts')

$scrip=Invoke-DunePlayerGiveScrip -Ip docker -ActorId $controller -Delta 0
Assert-Ok $scrip 'Scrip baseline'
$baseline=[long]$scrip.balance
$scrip=Invoke-DunePlayerGiveScrip -Ip docker -ActorId $controller -Delta 50
Assert-Ok $scrip 'Scrip grant'
if([long]$scrip.balance -ne $baseline+50){throw 'Scrip grant balance mismatch.'}
$restored=Invoke-DunePlayerGiveScrip -Ip docker -ActorId $controller -Delta -50
Assert-Ok $restored 'Scrip debit'
if([long]$restored.balance -ne $baseline){throw 'Scrip debit did not restore balance.'}
$intelSql="SELECT properties #>> '{TechKnowledgePlayerComponent,m_TechKnowledgePoints}' AS intel FROM dune.actors WHERE id=$pawn;"
$baseline=[long](Read-One $intelSql).intel
$intel=Invoke-DunePlayerAwardIntel -Ip docker -PawnId $pawn -IntelDelta 7
Assert-Ok $intel 'Intel grant'
if([long](Read-One $intelSql).intel -ne $baseline+7){throw 'Intel grant readback mismatch.'}
$checks.Add('Scrip grant/debit and Intel grant use the existing native currency model')

$xp=Invoke-DunePlayerGetCharXp -Ip docker -ActorId $pawn
Assert-Ok $xp 'Character XP baseline';$oldXp=[long]$xp.xp
$awarded=Invoke-DunePlayerAwardCharXp -Ip docker -PawnId $pawn -XpDelta 10
Assert-Ok $awarded 'Character XP grant'
$xp=Invoke-DunePlayerGetCharXp -Ip docker -ActorId $pawn
Assert-Ok $xp 'Character XP readback'
if([long]$xp.xp -ne $oldXp+10){throw 'Character XP grant did not round-trip.'}
$checks.Add('Offline character XP grant updates the pawn progression component')

$track=[string](Read-One 'SELECT unnest(enum_range(NULL::dune.specializationtracktype))::text AS track LIMIT 1;').track
$spec=Invoke-DunePlayerSetSpecLevel -Ip docker -ControllerId $controller -TrackType $track -Level 12
Assert-Ok $spec 'Specialization level'
$detail=Get-DunePlayerDetailLive -Ip docker -PawnId $pawn -ControllerId $controller
Assert-Ok $detail 'Specialization readback'
$found=$false;foreach($entry in $detail.specs){if($entry.track_type -ceq $track -and [double]$entry.level -eq 12){$found=$true}}
if(-not $found){throw 'Specialization level did not round-trip.'}
$applied=Invoke-DunePlayerApplySpecLevel -Ip docker -ControllerId $controller -TrackType $track -Level 13
Assert-Ok $applied 'Specialization rewards'
$checks.Add('Specialization level and reward application run through native PostgreSQL')

$faction=Invoke-DunePlayerGiveFactionRep -Ip docker -ActorId $controller -FactionId 1 -Delta 100
Assert-Ok $faction 'Faction reputation'
$tier=Invoke-DunePlayerSetFactionTier -Ip docker -ActorId $controller -FactionId 1 -Tier 4
Assert-Ok $tier 'Faction tier'
$cross=Invoke-DunePlayerGiveFactionRep -Ip docker -ActorId $controller -FactionId 2 -Delta 1
if($cross.ok){throw 'Cross-faction guard allowed conflicting allegiance.'}
$checks.Add('Faction standing and tier writes retain cross-faction protection')

@{ok=$true;scope='Isolated restored-copy database';checks=@($checks)} | ConvertTo-Json -Depth 4
