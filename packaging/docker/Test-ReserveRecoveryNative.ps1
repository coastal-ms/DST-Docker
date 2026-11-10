. /qualification-base.ps1 -InitializeOnly
. /opt/dst/app/server/lib/ReserveRecovery.ps1
$controller=[long]$player.controller_id
function Read-One([string]$Sql){
    $r=Invoke-DuneSqlQuery -Ip docker -ReadOnly $true -Sql $Sql -MaxRows 1
    Assert-Ok $r 'Readback';return (ConvertTo-DuneRowMaps -Result $r)[0]
}
# Native main-world scope and backup adapters have separate integration proof.
# Bind this SQL/journal qualification explicitly to the restored-copy OID.
function Get-DuneVehicleHostScope {
    param($Ip)
    $identity=Read-One 'SELECT current_database() AS database,(SELECT oid::text FROM pg_database WHERE datname=current_database()) AS oid;'
    if($identity.database -cne $settings.database){throw 'Qualification database changed.'}
    return @{key="qualification:$($identity.database):$($identity.oid)"}
}
function Invoke-DuneVerifiedSafetyBackup {
    param($Ip,$StemPrefix,$ProofLabel)
    $manifest=Get-Content /qualification-backup.json -Raw | ConvertFrom-Json
    $file=Get-Item /qualification-before-reserve.dump
    if($manifest.database -cne $settings.database -or $file.Length -ne $manifest.bytes -or
       (Get-FileHash $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -cne $manifest.sha256){throw 'Qualification backup does not match its verified manifest.'}
    return @{ok=$true;database_scope=(Get-DuneVehicleHostScope docker).key;path=$file.FullName;bytes=$file.Length}
}
$snapshot=Get-DuneReserveSnapshot -Ip docker -PawnId $pawn -ControllerId $controller
Assert-Ok $snapshot 'Reserve snapshot'
if($snapshot.reserve_count -gt 1 -or $snapshot.backpack_count -ne 1 -or @($snapshot.reserve_items).Count){throw 'Qualification requires one Backpack and an empty or absent Reserve.'}
$backpack=[long]$snapshot.backpack_inventory.id
$oldSlots=[int]$snapshot.backpack_inventory.max_item_count
$oldVolume=Format-DuneFloatForSql ([double]$snapshot.backpack_inventory.max_item_volume)
$reserve=0L;$created=$false;$itemId=0L;$holding=0L
try {
    # Earlier qualification intentionally created catalog-miss gear. Keep
    # those copy-only rows intact outside this positive capacity fixture.
    $r=Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "INSERT INTO dune.inventories(actor_id,inventory_type,max_item_count,max_item_volume) VALUES($pawn,99,1000,1000000) RETURNING id::text;" -MaxRows 1
    Assert-Ok $r 'Qualification holding inventory';$holding=[long](ConvertTo-DuneRowMaps -Result $r)[0].id
    Assert-Ok (Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "UPDATE dune.items SET inventory_id=$holding WHERE inventory_id=$backpack;") 'Hold existing copied items'
    if($snapshot.reserve_count -eq 0){
        $r=Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "INSERT INTO dune.inventories(actor_id,inventory_type,max_item_count,max_item_volume) VALUES($pawn,33,1000,1000000) RETURNING id::text;" -MaxRows 1
        Assert-Ok $r 'Reserve fixture';$reserve=[long](ConvertTo-DuneRowMaps -Result $r)[0].id;$created=$true
        Assert-Ok (Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "INSERT INTO dune.actor_inventories(inventory_id,component_name_hash) VALUES($reserve,-689927216);") 'Reserve actor component'
    }else{$reserve=[long]$snapshot.reserve_inventory.id}
    Assert-Ok (Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "UPDATE dune.inventories SET max_item_count=1000,max_item_volume=1000000 WHERE id=$backpack;") 'Qualification backpack capacity'
    $item=Invoke-DunePlayerGiveItem -Ip docker -PawnId $pawn -Template ScrapMetalKnife -Qty 1 -Quality 0
    Assert-Ok $item 'Reserve item fixture';$itemId=[long]$item.item_id
    Assert-Ok (Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "UPDATE dune.items SET inventory_id=$reserve,position_index=0 WHERE id=$itemId;") 'Move qualification item into Reserve'
    $preview=Get-DuneReserveRecoveryPreview -Ip docker -PawnId $pawn -ControllerId $controller
    Assert-Ok $preview 'Reserve preview'
    if(-not $preview.available){throw "Native preview was blocked: $($preview.blocked_reason)"}
    Assert-Ok (Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "UPDATE dune.items SET quality_level=1 WHERE id=$itemId;") 'Stale revision fixture'
    $stale=Invoke-DuneReserveRecovery -Ip docker -PawnId $pawn -ControllerId $controller -Revision $preview.revision
    if($stale.ok){throw 'Stale Reserve preview was accepted.'}
    $preview=Get-DuneReserveRecoveryPreview -Ip docker -PawnId $pawn -ControllerId $controller
    Assert-Ok $preview 'Refreshed preview'
    $moved=Invoke-DuneReserveRecovery -Ip docker -PawnId $pawn -ControllerId $controller -Revision $preview.revision
    Assert-Ok $moved 'Native Reserve recovery'
    $row=Read-One "SELECT inventory_id::text AS inventory,quality_level::text AS quality FROM dune.items WHERE id=$itemId;"
    if([long]$row.inventory -ne $backpack -or [long]$row.quality -ne 1){throw 'Recovery changed item identity or did not reach Backpack.'}
    $state=Read-DuneReserveRecoveryState
    if(@($state.entries | Where-Object recovery_id -eq $moved.recovery_id).Count -ne 1){throw 'Native journal did not persist the recovery before-image.'}
    $rolled=Invoke-DuneReserveRecoveryRollback -Ip docker -PawnId $pawn -ControllerId $controller -RecoveryId $moved.recovery_id
    Assert-Ok $rolled 'Exact native rollback'
    $row=Read-One "SELECT inventory_id::text AS inventory,position_index::text AS position,quality_level::text AS quality FROM dune.items WHERE id=$itemId;"
    if([long]$row.inventory -ne $reserve -or [int]$row.position -ne 0 -or [long]$row.quality -ne 1){throw 'Rollback did not restore the exact Reserve item.'}
    $checks.Add('Native Reserve preview rejects stale revisions, persists the before-image, moves the same item intact and rolls it back exactly')
} finally {
    if($itemId -gt 0){Assert-Ok (Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "DELETE FROM dune.items WHERE id=$itemId;") 'Remove qualification item'}
    if($created -and $reserve -gt 0){Assert-Ok (Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "DELETE FROM dune.actor_inventories WHERE inventory_id=$reserve; DELETE FROM dune.inventories WHERE id=$reserve;") 'Remove Reserve fixture'}
    if($holding -gt 0){Assert-Ok (Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "UPDATE dune.items SET inventory_id=$backpack WHERE inventory_id=$holding; DELETE FROM dune.inventories WHERE id=$holding;") 'Restore copied Backpack items'}
    Assert-Ok (Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql "UPDATE dune.inventories SET max_item_count=$oldSlots,max_item_volume=$oldVolume WHERE id=$backpack;") 'Restore Backpack capacity'
}
@{ok=$true;checks=$checks.ToArray();scopeAndBackupBoundary='Restored-copy fixture; production adapters qualified separately';liveWorldMutated=$false} | ConvertTo-Json -Depth 4
