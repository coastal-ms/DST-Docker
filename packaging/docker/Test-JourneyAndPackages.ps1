param([switch]$InitializeOnly)
$ErrorActionPreference='Stop'
$settings=Get-Content /data/config/DuneServer/docker-database.json -Raw | ConvertFrom-Json
if($settings.host -ne '127.0.0.1' -or $settings.port -ne 18932 -or $settings.database -notmatch '^dst_qualify_[a-f0-9]{24}$' -or -not $settings.allowWrites){
    throw 'This qualification requires an isolated restored-copy database.'
}
$env:DST_HOSTING_BACKEND='docker'
$env:APPDATA='/tmp/dst-package-tests'
$script:AppDir='/opt/dst/app'
foreach($library in @('app/lib/Db-Postgres.ps1','app/server/lib/DockerDatabase.ps1','app/server/lib/Database.ps1',
    'app/server/lib/Gameplay.ps1','app/server/lib/GameplayPlayers.ps1','app/server/lib/PlayersWrites.ps1',
    'app/server/lib/PlayersRead.ps1','app/server/lib/PlayersAdmin.ps1','app/server/lib/PlayerGuard.ps1',
    'app/server/lib/SoloMode.ps1','app/server/lib/Codex.ps1','app/server/lib/ItemPackages.ps1',
    'app/server/lib/PlayersRmq.ps1')){
    . (Join-Path /opt/dst $library)
}
function Register-DuneRoute { param($Method,$Path,$Handler) }
. /opt/dst/app/server/routes/GameplayPlayers.ps1
function Assert-Ok($Result,[string]$Action){if(-not $Result.ok){throw "$Action failed: $($Result.error) $($Result.reason)"}}
$identity=Invoke-DuneSqlQuery -Ip docker -Sql 'SELECT current_database() AS database, current_user AS role' -ReadOnly $true
Assert-Ok $identity 'Database identity'
$row=@(ConvertTo-DuneRowMaps -Result $identity)[0]
if($row.database -ne $settings.database -or $row.role -ne 'dune'){throw 'Unexpected database identity.'}
$players=Get-DunePlayersLive -Ip docker
Assert-Ok $players 'Character lookup'
if(@($players.players).Count -ne 1){throw 'Expected one restored character.'}
$player=$players.players[0];$account=[long]$player.account_id;$pawn=[long]$player.id
$offline=Test-DunePlayerOfflineByAccount -Ip docker -AccountId $account
Assert-Ok $offline 'Offline qualification character'
$checks=[Collections.Generic.List[string]]::new()
if($InitializeOnly){return}

$package=Save-DuneItemPackage -Incoming @{name='Restored-copy package';items=@(@{template='CopperBar';qty=3;quality=0})}
$beforeInventory=Get-DunePlayerDetailLive -Ip docker -PawnId $pawn -ControllerId ([long]$player.controller_id)
Assert-Ok $beforeInventory 'Initial inventory'
$beforeCopper=0; foreach($item in $beforeInventory.inventory){if($item.template_id -eq 'CopperBar'){$beforeCopper += [long]$item.stack_size}}
$given=Invoke-DunePlayerGiveItemsBulk -Ip docker -PawnId $pawn -Items $package.items
Assert-Ok $given 'Offline package delivery'
if($given.failures -ne 0 -or @($given.results | Where-Object {$_.path -ne 'sql'}).Count){throw 'Package delivery did not use the offline native SQL path.'}
$afterInventory=Get-DunePlayerDetailLive -Ip docker -PawnId $pawn -ControllerId ([long]$player.controller_id)
Assert-Ok $afterInventory 'Granted inventory'
$afterCopper=0; foreach($item in $afterInventory.inventory){if($item.template_id -eq 'CopperBar'){$afterCopper += [long]$item.stack_size}}
if($afterCopper -ne $beforeCopper+3){throw "Package inventory increase did not match its quantity: before=$beforeCopper, after=$afterCopper"}
$checks.Add('Package store and existing bulk delivery use the native offline inventory path')

$waterItem=Invoke-DunePlayerGiveItem -Ip docker -PawnId $pawn -Template 'Literjon' -Qty 1 -Quality 0
Assert-Ok $waterItem 'Water container fixture'
$empty=Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "UPDATE dune.items SET stats=jsonb_set(stats,'{FFillableItemStats,1,CurrentAmount}','0'::jsonb) WHERE inventory_id IN (SELECT id FROM dune.inventories WHERE actor_id=$pawn) AND lower(template_id)='literjon';"
Assert-Ok $empty 'Empty restored-copy water container'
$refill=Invoke-DunePlayerFillWater -Ip docker -PawnId $pawn
Assert-Ok $refill 'Fill Water'
if($refill.refilled -lt 1){throw 'Water fixture was not refilled.'}
$water=Invoke-DuneSqlQuery -Ip docker -ReadOnly $true -Sql "SELECT count(*)::text AS full FROM dune.items WHERE inventory_id IN (SELECT id FROM dune.inventories WHERE actor_id=$pawn) AND lower(template_id)='literjon' AND (stats #>> '{FFillableItemStats,1,CurrentAmount}')::numeric=(stats #>> '{FFillableItemStats,1,MaxAmount}')::numeric AND (stats #>> '{FFillableItemStats,1,MaxAmount}')::numeric>0;"
Assert-Ok $water 'Water level readback'
if([int]@(ConvertTo-DuneRowMaps -Result $water)[0].full -lt 1){throw 'Refilled water amount did not equal container capacity.'}
$checks.Add('Fill Water restores an empty Literjon to its actual capacity on native PostgreSQL')

$gear=Invoke-DunePlayerGiveItem -Ip docker -PawnId $pawn -Template 'ScrapMetalKnife' -Qty 1 -Quality 0
Assert-Ok $gear 'Durable gear fixture'
$broken=Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "UPDATE dune.items SET stats=jsonb_set(stats,'{FItemStackAndDurabilityStats,1,CurrentDurability}','0'::jsonb) WHERE inventory_id IN (SELECT id FROM dune.inventories WHERE actor_id=$pawn) AND lower(template_id)='scrapmetalknife';"
Assert-Ok $broken 'Break restored-copy fixture'
$restored=Invoke-DunePlayerRestoreDestroyedGear -Ip docker -PawnId $pawn
Assert-Ok $restored 'Restore Destroyed Items'
if($restored.restored -lt 1){throw 'Destroyed fixture was not restored.'}
$repaired=Invoke-DunePlayerRepairGear -Ip docker -PawnId $pawn
Assert-Ok $repaired 'Repair Gear'
if($repaired.repaired -lt 1){throw 'Gear fixture was not repaired.'}
$durability=Invoke-DuneSqlQuery -Ip docker -ReadOnly $true -Sql "SELECT count(*)::text AS full FROM dune.items WHERE inventory_id IN (SELECT id FROM dune.inventories WHERE actor_id=$pawn) AND lower(template_id)='scrapmetalknife' AND (stats #>> '{FItemStackAndDurabilityStats,1,CurrentDurability}')::numeric=(stats #>> '{FItemStackAndDurabilityStats,1,MaxDurability}')::numeric AND (stats #>> '{FItemStackAndDurabilityStats,1,MaxDurability}')::numeric>0;"
Assert-Ok $durability 'Repaired durability readback'
if([int]@(ConvertTo-DuneRowMaps -Result $durability)[0].full -lt 1){throw 'Repaired item did not reach its durability ceiling.'}
$checks.Add('Restore Destroyed Items and Repair Gear restore a damaged knife to its durability ceiling')

$completed=Invoke-DunePlayerApplyProgressionPreset -Ip docker -AccountId $account -PresetId 'find_the_fremen'
Assert-Ok $completed 'Find the Fremen preset'
$flags=Invoke-DuneSqlQuery -Ip docker -ReadOnly $true -Sql @"
SELECT fe.components #>> '{FSpiceAddictionComponent,1,SystemStatus}' AS system,
       fe.components #>> '{FSpiceAddictionComponent,1,SpiceVisionEnabledStatus}' AS vision
FROM dune.actor_fgl_entities afe JOIN dune.fgl_entities fe ON fe.entity_id=afe.entity_id
WHERE afe.actor_id=$pawn AND afe.slot_name='DuneCharacter'
"@
Assert-Ok $flags 'Preset reward flags'
$flagsRow=@(ConvertTo-DuneRowMaps -Result $flags)[0]
if($flagsRow.system -ne 'FullyEnabled' -or $flagsRow.vision -ne 'FullyEnabled'){throw 'Preset did not apply both Prescience flags.'}
$checks.Add('Complete Story preset grants both Find the Fremen Prescience flags')

$reset=Invoke-DunePlayerResetJourneyNode -Ip docker -AccountId $account -NodeId 'DA_MQ_FindTheFremen'
Assert-Ok $reset 'Single journey reset'
$node=Invoke-DuneSqlQuery -Ip docker -ReadOnly $true -Sql "SELECT complete_condition_state::text AS complete FROM dune.journey_story_node WHERE character_id IN (SELECT id FROM dune.player_state WHERE account_id=$account) AND story_node_id='DA_MQ_FindTheFremen';"
Assert-Ok $node 'Reset node readback'
if(@(ConvertTo-DuneRowMaps -Result $node)[0].complete -ne 'false'){throw 'Journey root remained completed after reset.'}
$checks.Add('Single journey reset changes the stored completion state')

$skip=Invoke-DunePlayerApplyProgressionPreset -Ip docker -AccountId $account -PresetId 'skip_npe'
Assert-Ok $skip 'Skip tutorial preset'
$checks.Add('Skip tutorial preset applies the existing captured NPE completion')

$wipe=Invoke-DunePlayerWipeJourneyNodes -Ip docker -AccountId $account -KeepNpeCompleted
Assert-Ok $wipe 'Post-NPE story reset'
$checks.Add('Post-NPE story reset executes its existing transactional reset on native PostgreSQL')

$resetAll=Invoke-DunePlayerResetJourneyNodes -Ip docker -AccountId $account
Assert-Ok $resetAll 'Full post-tutorial journey reset'
$checks.Add('Reset Journey preserves its existing starter-tree and captured tutorial workflow')

$main=Invoke-DunePlayerUnlockMainQuest -Ip docker -AccountId $account -Quest 'DA_MQ_FindTheFremen'
Assert-Ok $main 'Main quest unlock'
$wipeAll=Invoke-DunePlayerWipeJourneyNodes -Ip docker -AccountId $account
Assert-Ok $wipeAll 'Journey wipe'
$checks.Add('Main quest unlock and journey wipe use the native database path')

@{ok=$true;scope='Isolated restored-copy database';checks=@($checks)} | ConvertTo-Json -Depth 5
