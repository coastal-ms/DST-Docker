function Get-DuneDockerPlayerCoordinateContext {
    param([string]$Ip,[long]$PawnId=0,[long]$AccountId=0)
    if($PawnId -le 0 -and $AccountId -le 0){return @{ok=$false;error='Select a player first.'}}
    $where=if($PawnId -gt 0){"s.player_pawn_id=$PawnId::bigint"}else{"s.account_id=$AccountId::bigint"}
    $sql=@"
SELECT s.id::text AS character_id,s.account_id::text AS account_id,s.player_pawn_id::text AS pawn_id,
       s.online_status::text AS status,account."user" AS fls_id,
       dune.upgrade_map_name(a.map) AS map,a.partition_id::text AS partition_id,
       a.dimension_index::text AS dimension,
       (a.transform).location.x::text AS x,(a.transform).location.y::text AS y,(a.transform).location.z::text AS z
FROM dune.encrypted_player_state s
JOIN dune.accounts account ON account.id=s.account_id
JOIN dune.actors a ON a.id=s.player_pawn_id AND a.owner_account_id=s.account_id
WHERE s.character_state='Active' AND $where;
"@
    $reply=Invoke-DuneSqlQuery -Ip $Ip -Sql $sql -ReadOnly $true -MaxRows 2 -TimeoutSec 15
    if(-not $reply.ok){return @{ok=$false;error='Player identity and status could not be verified. Refresh and try again.'}}
    $rows=ConvertTo-DuneRowMaps -Result $reply
    if($rows.Count -ne 1){return @{ok=$false;error='The selected player does not resolve to one active character. Refresh the player list.'}}
    $row=$rows[0]
    if(-not $row.fls_id -or -not $row.map -or [long]$row.partition_id -le 0){return @{ok=$false;error='The selected player has no verified account or map location.'}}
    $dimension=0
    if(-not [int]::TryParse([string]$row.dimension,[ref]$dimension) -or $dimension -lt 0){return @{ok=$false;error='The selected player has no verified map dimension.'}}
    foreach($key in @('x','y','z')){
        $value=0.0
        if(-not [double]::TryParse([string]$row[$key],[Globalization.NumberStyles]::Float,[cultureinfo]::InvariantCulture,[ref]$value) -or [double]::IsNaN($value) -or [double]::IsInfinity($value)){
            return @{ok=$false;error='The selected player has no valid coordinates.'}
        }
        $row[$key]=$value
    }
    return @{ok=$true;player=$row}
}

function Get-DuneDockerPlayerDestinationPartition {
    param([string]$Ip,[long]$PartitionId,[string]$ExpectedMap='')
    if($PartitionId -le 0){return @{ok=$false;error='The destination partition is unavailable.'}}
    $expected=ConvertTo-DuneSqlString $ExpectedMap
    $sql="SELECT partition_id::text AS partition_id,map AS raw_map,dune.upgrade_map_name(map) AS map,dimension_index::text AS dimension,blocked::text AS blocked,dune.upgrade_map_name('$expected') AS expected_map FROM dune.world_partition WHERE partition_id=$PartitionId::bigint;"
    $reply=Invoke-DuneSqlQuery -Ip $Ip -Sql $sql -ReadOnly $true -MaxRows 2 -TimeoutSec 15
    if(-not $reply.ok){return @{ok=$false;error='The destination partition could not be verified.'}}
    $rows=ConvertTo-DuneRowMaps -Result $reply
    if($rows.Count -ne 1){return @{ok=$false;error='That destination is unavailable in this world.'}}
    $row=$rows[0]
    if($row.blocked -match '^(true|t|1)$' -or -not $row.map -or ($ExpectedMap -and $row.map -cne $row.expected_map)){
        return @{ok=$false;error='That destination is unavailable in this world.'}
    }
    return @{ok=$true;partition=$row}
}

function ConvertTo-DuneDockerPlacementText {
    param([AllowEmptyString()][string]$Value)
    $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Value))
    return "convert_from(decode('$encoded','base64'),'UTF8')"
}

function Invoke-DuneDockerOfflinePlayerPlacement {
    param([string]$Ip,[hashtable]$Player,[hashtable]$Partition,[double]$X,[double]$Y,[double]$Z,
          [switch]$Respawn,[string]$RespawnMap='',[string]$Label='')
    if($Player.status -cne 'Offline'){return @{ok=$false;error='The player must finish logging out and show Offline before this change.'}}
    foreach($value in @($X,$Y,$Z)){if([double]::IsNaN($value) -or [double]::IsInfinity($value)){return @{ok=$false;error='Destination coordinates must be finite.'}}}
    $tokens=@{
        '__ACCOUNT__'=[string][long]$Player.account_id;'__CHARACTER__'=[string][long]$Player.character_id
        '__PAWN__'=[string][long]$Player.pawn_id;'__PARTITION__'=[string][long]$Partition.partition_id
        '__DIMENSION__'=[string][int]$Partition.dimension;'__MAP_SQL__'=(ConvertTo-DuneDockerPlacementText ([string]$Partition.map))
        '__FLS_SQL__'=(ConvertTo-DuneDockerPlacementText ([string]$Player.fls_id))
        '__X__'=$X.ToString('R',[cultureinfo]::InvariantCulture);'__Y__'=$Y.ToString('R',[cultureinfo]::InvariantCulture);'__Z__'=$Z.ToString('R',[cultureinfo]::InvariantCulture)
        '__RESPAWN_MAP_SQL__'=(ConvertTo-DuneDockerPlacementText $RespawnMap);'__GROUP_SQL__'=(ConvertTo-DuneDockerPlacementText ('Admin: '+$Label))
    }
    $sql=@'
DO $dst_placement$
DECLARE selected dune.encrypted_player_state%ROWTYPE; respawn_id uuid;
BEGIN
 SELECT * INTO STRICT selected FROM dune.encrypted_player_state
 WHERE account_id=__ACCOUNT__::bigint AND character_state='Active' FOR UPDATE;
 IF NOT FOUND OR selected.id<>__CHARACTER__::bigint OR selected.player_pawn_id IS DISTINCT FROM __PAWN__::bigint OR selected.online_status<>'Offline' THEN
  RAISE EXCEPTION 'The selected character or offline status changed. Refresh and try again.';
 END IF;
 PERFORM 1 FROM dune.actors a JOIN dune.encrypted_accounts account ON account.id=a.owner_account_id
 WHERE a.id=__PAWN__::bigint AND account.id=__ACCOUNT__::bigint AND account."user"=__FLS_SQL__ FOR SHARE OF account;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'The selected player identity changed. Refresh and try again.';
 END IF;
 PERFORM 1 FROM dune.world_partition WHERE partition_id=__PARTITION__::bigint AND NOT blocked
 AND dune.upgrade_map_name(map)=__MAP_SQL__ AND dimension_index=__DIMENSION__::int FOR SHARE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'The destination changed or is unavailable. Refresh and try again.';
 END IF;
 __PLACEMENT__
END;
$dst_placement$;
__RESULT__
'@
    if($Respawn){
        $placement=@'
 INSERT INTO dune.player_respawn_locations
 (id,character_id,"group",locator_transform,locator_actor_id,locator_name,locator_name_index,map,dimension,last_used_timestamp)
 VALUES(gen_random_uuid(),__CHARACTER__::bigint,__GROUP_SQL__,
 ROW(ROW(__X__::float8,__Y__::float8,__Z__::float8)::dune.vector,ROW(0,0,0,1)::dune.quaternion)::dune.transform,
 NULL,NULL,0,__RESPAWN_MAP_SQL__,__DIMENSION__::int,(extract(epoch FROM now())*1000)::bigint)
 RETURNING id INTO respawn_id;
 IF respawn_id IS NULL OR NOT EXISTS(SELECT 1 FROM dune.player_respawn_locations
 WHERE id=respawn_id AND character_id=__CHARACTER__::bigint AND map=__RESPAWN_MAP_SQL__ AND dimension=__DIMENSION__::int
 AND abs((locator_transform).location.x-(__X__::float8))<0.00001
 AND abs((locator_transform).location.y-(__Y__::float8))<0.00001
 AND abs((locator_transform).location.z-(__Z__::float8))<0.00001) THEN
  RAISE EXCEPTION 'The respawn point could not be verified; no change was kept.';
 END IF;
'@
        $result="SELECT '__CHARACTER__'::text AS character_id;"
    }else{
        $placement=@'
 PERFORM dune.admin_move_offline_player_to_partition(__FLS_SQL__,__PARTITION__::bigint,ROW(__X__::float8,__Y__::float8,__Z__::float8)::dune.vector);
 IF NOT EXISTS(SELECT 1 FROM dune.actors WHERE id=__PAWN__::bigint AND partition_id=__PARTITION__::bigint
               AND dune.upgrade_map_name(map)=__MAP_SQL__ AND dimension_index=__DIMENSION__::int
               AND abs((transform).location.x-(__X__::float8))<0.00001
               AND abs((transform).location.y-(__Y__::float8))<0.00001
               AND abs((transform).location.z-(__Z__::float8))<0.00001) THEN
  RAISE EXCEPTION 'The player move could not be verified; no change was kept.';
 END IF;
'@
        $result='SELECT id::text AS pawn_id FROM dune.actors WHERE id=__PAWN__::bigint;'
    }
    $sql=$sql.Replace('__PLACEMENT__',$placement).Replace('__RESULT__',$result)
    $sql=[regex]::Replace($sql,'__[A-Z_]+__',[Text.RegularExpressions.MatchEvaluator]{param($match);[string]$tokens[$match.Value]})
    $reply=Invoke-DuneSqlQuery -Ip $Ip -Sql $sql -ReadOnly $false -MaxRows 1 -TimeoutSec 30
    if(-not $reply.ok){return @{ok=$false;error=('The player change was not applied. '+[string]$reply.error)}}
    return @{ok=$true;path='sql';partition=[long]$Partition.partition_id;x=$X;y=$Y;z=$Z;
        message=$(if($Respawn){"Added a respawn point at $Label. Existing respawn points were preserved."}else{'Moved the offline player. The change applies on next login.'})}
}

function Invoke-DuneDockerPlayerTeleportToPlayer {
    param([string]$Ip,[long]$SourcePawnId,[long]$TargetPawnId,[Nullable[long]]$PartitionId=$null)
    if($SourcePawnId -le 0 -or $TargetPawnId -le 0){return @{ok=$false;error='Select both players first.'}}
    $source=Get-DuneDockerPlayerCoordinateContext -Ip $Ip -PawnId $SourcePawnId
    if(-not $source.ok){return $source}
    $target=Get-DuneDockerPlayerCoordinateContext -Ip $Ip -PawnId $TargetPawnId
    if(-not $target.ok){return $target}
    $src=$source.player;$dst=$target.player
    $part=[long]$dst.partition_id
    if($null -ne $PartitionId -and [long]$PartitionId -ne $part){return @{ok=$false;error='The destination partition must match the target player.'}}
    $partition=Get-DuneDockerPlayerDestinationPartition -Ip $Ip -PartitionId $part -ExpectedMap ([string]$dst.map)
    if(-not $partition.ok){return $partition}
    if([int]$partition.partition.dimension -ne [int]$dst.dimension){return @{ok=$false;error='The target player location changed. Refresh the player list.'}}
    if($src.status -ceq 'Offline'){
        return Invoke-DuneDockerOfflinePlayerPlacement -Ip $Ip -Player $src -Partition $partition.partition -X $dst.x -Y $dst.y -Z $dst.z
    }
    if($src.status -cne 'Online'){return @{ok=$false;error='Wait until the player finishes connecting or logging out, then refresh.'}}
    if($src.map -cne $dst.map -or [long]$src.partition_id -ne $part -or [int]$src.dimension -ne [int]$dst.dimension){
        return @{ok=$false;error='Online players must be in the same map, partition and dimension. Travel to the target map first.'}
    }
    $reply=Invoke-DuneRmqTeleportToExact -FlsId ([string]$src.fls_id) -X $dst.x -Y $dst.y -Z $dst.z
    if(-not $reply.ok){return @{ok=$false;error=[string]$reply.message}}
    $reply.message='Teleport requested for the online player.';$reply.path='rmq';$reply.x=$dst.x;$reply.y=$dst.y;$reply.z=$dst.z
    return $reply
}

function Invoke-DuneDockerPlayerDestinationPlacement {
    param([string]$Ip,[long]$AccountId,[string]$Destination,[switch]$Respawn)
    $dest=Get-DuneTeleportDestinationById -Id $Destination
    if(-not $dest){return @{ok=$false;error='Choose a destination from the available list.'}}
    $context=Get-DuneDockerPlayerCoordinateContext -Ip $Ip -AccountId $AccountId
    if(-not $context.ok){return $context}
    $partition=Get-DuneDockerPlayerDestinationPartition -Ip $Ip -PartitionId ([long]$dest.partition) -ExpectedMap ([string]$dest.respawnMap)
    if(-not $partition.ok){return $partition}
    return Invoke-DuneDockerOfflinePlayerPlacement -Ip $Ip -Player $context.player -Partition $partition.partition -X $dest.x -Y $dest.y -Z $dest.z -Respawn:$Respawn -RespawnMap $dest.respawnMap -Label $dest.label
}
