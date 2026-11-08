function Get-DuneDockerFreshStartPath {
    $reply=Invoke-DuneDockerManager -Request @{action='status'}
    if(-not $reply.ok -or $reply.data.projectId -notmatch '^[a-f0-9]{32}$'){throw 'The Docker world for purchase snapshots could not be verified.'}
    $folder=Join-Path $env:APPDATA 'DuneServer/fresh-start-snapshots'
    return Join-Path $folder ($reply.data.projectId+'.json')
}

function Read-DuneDockerFreshStartStore {
    param([string]$Path)
    $project=[IO.Path]::GetFileNameWithoutExtension($Path)
    if(-not [IO.File]::Exists($Path)){return @{format=1;project_id=$project;snapshots=@()}}
    try{
        $document=[IO.File]::ReadAllText($Path) | ConvertFrom-Json -AsHashtable -DateKind String -Depth 100 -ErrorAction Stop
        if($document.format -ne 1 -or $document.project_id -cne $project -or $document.snapshots -isnot [Collections.IList]){throw 'Unexpected snapshot format.'}
        foreach($entry in $document.snapshots){
            if($entry -isnot [Collections.IDictionary] -or -not $entry.name -or -not $entry.fls_id -or [string]$entry.account_id -notmatch '^[1-9][0-9]*$'){throw 'Invalid snapshot identity.'}
            if($entry.building_sets -isnot [Collections.IList] -or $entry.buildable_pieces -isnot [Collections.IList]){throw 'Invalid snapshot building data.'}
            if($null -ne $entry.cosmetics -and $entry.cosmetics -isnot [Collections.IDictionary]){throw 'Invalid snapshot cosmetics.'}
            if($null -ne $entry.cosmetics -and $entry.cosmetics.Contains('m_UnlockedCustomizationIds') -and $entry.cosmetics.m_UnlockedCustomizationIds -isnot [Collections.IList]){throw 'Invalid snapshot cosmetic unlocks.'}
        }
        return $document
    }catch{throw 'Purchase snapshots could not be read. Restore their configuration file before saving another snapshot.'}
}

function Get-DuneDockerFreshStartRestoreSql {
    param([long]$AccountId,[hashtable]$Payload,[bool]$SkipNpe)
    $json=ConvertTo-Json -InputObject $Payload -Depth 100 -Compress
    $sql=@'
DO $dst_purchases$
DECLARE selected dune.encrypted_player_state%ROWTYPE; pawn dune.actors%ROWTYPE; requested jsonb;
        expected_sets text[]; expected_pieces text[]; entry text; current_cosmetics jsonb;
        saved_cosmetics jsonb; current_ids jsonb; saved_ids jsonb; unlocked jsonb;
        cosmetic_root jsonb; expected_properties jsonb; expected_cosmetics jsonb;
        nodes text[]; had_builds boolean;
BEGIN
 requested:=__PAYLOAD__::jsonb;
 SELECT * INTO STRICT selected FROM dune.encrypted_player_state
 WHERE account_id=__ACCOUNT__::bigint AND character_state='Active' FOR UPDATE;
 IF selected.online_status<>'Offline' THEN
  RAISE EXCEPTION 'The character must finish logging out and show Offline before restoring purchases.';
 END IF;
 PERFORM 1 FROM dune.encrypted_accounts WHERE id=selected.account_id AND "user"=requested->>'fls_id' FOR SHARE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'The snapshot belongs to a different account identity. No purchases were restored.';
 END IF;
 SELECT * INTO STRICT pawn FROM dune.actors WHERE id=selected.player_pawn_id AND owner_account_id=selected.account_id FOR UPDATE;
 IF pawn.properties IS NOT NULL AND jsonb_typeof(pawn.properties)<>'object' THEN RAISE EXCEPTION 'The current character properties format is unsupported.'; END IF;
 SELECT learned_building_sets,new_buildable_pieces INTO expected_sets,expected_pieces
 FROM dune.building_progression WHERE character_id=selected.id FOR UPDATE;
 had_builds:=FOUND;
 FOR entry IN SELECT jsonb_array_elements_text(requested->'sets') LOOP
  IF array_position(expected_sets,entry) IS NULL THEN expected_sets:=array_append(expected_sets,entry); END IF;
 END LOOP;
 FOR entry IN SELECT jsonb_array_elements_text(requested->'pieces') LOOP
  IF array_position(expected_pieces,entry) IS NULL THEN expected_pieces:=array_append(expected_pieces,entry); END IF;
 END LOOP;
 IF had_builds THEN
  UPDATE dune.building_progression SET learned_building_sets=expected_sets,new_buildable_pieces=expected_pieces WHERE character_id=selected.id;
 ELSIF cardinality(expected_sets)>0 OR cardinality(expected_pieces)>0 THEN
  INSERT INTO dune.building_progression(character_id,learned_building_sets,new_buildable_pieces) VALUES(selected.id,expected_sets,expected_pieces);
  had_builds:=true;
 END IF;
 IF had_builds AND NOT EXISTS(SELECT 1 FROM dune.building_progression WHERE character_id=selected.id
    AND learned_building_sets IS NOT DISTINCT FROM expected_sets AND new_buildable_pieces IS NOT DISTINCT FROM expected_pieces) THEN
  RAISE EXCEPTION 'The building purchase restore could not be verified. No changes were saved.';
 END IF;
 saved_cosmetics:=NULLIF(requested->'cosmetics','null'::jsonb);
 IF saved_cosmetics IS NOT NULL AND saved_cosmetics<>'{}'::jsonb THEN
  IF jsonb_typeof(saved_cosmetics)<>'object' THEN RAISE EXCEPTION 'The saved cosmetics format is unsupported.'; END IF;
  cosmetic_root:=COALESCE(NULLIF(pawn.properties->'CustomizationLibraryActorComponent','null'::jsonb),'{}'::jsonb);
  IF jsonb_typeof(cosmetic_root)<>'object' THEN RAISE EXCEPTION 'The current cosmetics component format is unsupported.'; END IF;
  current_cosmetics:=COALESCE(NULLIF(cosmetic_root->'m_UnlockedCustomizationSerializableList','null'::jsonb),'{}'::jsonb);
  IF jsonb_typeof(current_cosmetics)<>'object' THEN RAISE EXCEPTION 'The current cosmetics format is unsupported.'; END IF;
  current_ids:=COALESCE(current_cosmetics->'m_UnlockedCustomizationIds','[]'::jsonb);
  saved_ids:=COALESCE(saved_cosmetics->'m_UnlockedCustomizationIds','[]'::jsonb);
  IF jsonb_typeof(current_ids)<>'array' OR jsonb_typeof(saved_ids)<>'array' THEN RAISE EXCEPTION 'The cosmetics unlock list format is unsupported.'; END IF;
  FOR unlocked IN SELECT jsonb_array_elements(saved_ids) LOOP
   IF NOT current_ids @> jsonb_build_array(unlocked) THEN current_ids:=current_ids||jsonb_build_array(unlocked); END IF;
  END LOOP;
  expected_cosmetics:=saved_cosmetics||current_cosmetics||jsonb_build_object('m_UnlockedCustomizationIds',current_ids);
  expected_properties:=COALESCE(pawn.properties,'{}'::jsonb)||jsonb_build_object('CustomizationLibraryActorComponent',
    cosmetic_root||jsonb_build_object('m_UnlockedCustomizationSerializableList',expected_cosmetics));
  UPDATE dune.actors SET properties=expected_properties WHERE id=pawn.id;
  IF NOT EXISTS(SELECT 1 FROM dune.actors WHERE id=pawn.id AND owner_account_id=selected.account_id AND properties=expected_properties) THEN
   RAISE EXCEPTION 'The cosmetic purchase restore could not be verified. No changes were saved.';
  END IF;
 END IF;
 __NPE__
END;
$dst_purchases$;
'@
    $npe=if($SkipNpe){@'
 SELECT array_agg(value) INTO nodes FROM jsonb_array_elements_text(requested->'nodes');
 IF cardinality(nodes) IS NULL OR cardinality(nodes)=0 THEN RAISE EXCEPTION 'The tutorial completion catalog is empty.'; END IF;
 INSERT INTO dune.player_tags(character_id,tag) VALUES(selected.id,'NPE.HasCompletedNPE') ON CONFLICT DO NOTHING;
 UPDATE dune.journey_story_node SET complete_condition_state='true'::jsonb,reveal_condition_state='true'::jsonb,has_pending_reward=false
 WHERE character_id=selected.id AND story_node_id=ANY(nodes);
 INSERT INTO dune.journey_story_node(character_id,story_node_id,has_pending_reward,complete_condition_state,reveal_condition_state,fail_condition_state,metadata_state,reset_group)
 SELECT selected.id,unnest(nodes),false,'true'::jsonb,'true'::jsonb,'{}'::jsonb,'{}'::jsonb,'Default'::dune.JourneyStoryResetGroup ON CONFLICT(character_id,story_node_id) DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM dune.player_tags WHERE character_id=selected.id AND tag='NPE.HasCompletedNPE')
 OR (SELECT count(*) FROM dune.journey_story_node WHERE character_id=selected.id AND story_node_id=ANY(nodes)
     AND complete_condition_state='true'::jsonb AND reveal_condition_state='true'::jsonb AND NOT has_pending_reward)<>cardinality(nodes) THEN
  RAISE EXCEPTION 'The tutorial completion could not be verified. No changes were saved.';
 END IF;
'@}else{''}
    return $sql.Replace('__ACCOUNT__',[string]$AccountId).Replace('__PAYLOAD__',(ConvertTo-DuneDockerPlacementText $json)).Replace('__NPE__',$npe)
}

function Save-DuneDockerFreshStartStore {
    param([string]$Path,[hashtable]$Store)
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path))
    $temporary=$Path+'.'+[guid]::NewGuid().ToString('N')+'.tmp'
    try{
        [IO.File]::WriteAllText($temporary,(ConvertTo-Json -InputObject $Store -Depth 100),[Text.UTF8Encoding]::new($false))
        [IO.File]::Move($temporary,$Path,$true)
    }finally{if([IO.File]::Exists($temporary)){[IO.File]::Delete($temporary)}}
}

function Get-DuneDockerFreshStartSnapshotList {
    $path=Get-DuneDockerFreshStartPath
    $gate=[string]::Intern('DST.Docker.FreshStart.Snapshots')
    [Threading.Monitor]::Enter($gate)
    try{
        $store=Read-DuneDockerFreshStartStore -Path $path
        $list=@(foreach($entry in $store.snapshots){
            @{name=[string]$entry.name;account_id=[string]$entry.account_id;saved_at=[string]$entry.saved_at;
              sets=@($entry.building_sets).Count;pieces=@($entry.buildable_pieces).Count;cosmetics=[bool]$entry.cosmetics}
        })
        return ,$list
    }finally{[Threading.Monitor]::Exit($gate)}
}

function ConvertTo-DuneDockerPurchasedBuilds {
    param($Values)
    $purchased=[Collections.Generic.List[string]]::new()
    foreach($value in $Values){
        if($null -eq $value){continue}
        if($value -isnot [string]){throw 'The purchase snapshot contains unsupported building data.'}
        if($value -match '^(MTX_|Choam)'){[void]$purchased.Add($value)}
    }
    return ,@($purchased)
}

function Invoke-DuneDockerPlayerSnapshotBuilds {
    param([string]$Ip,[long]$AccountId)
    if($AccountId -le 0){return @{ok=$false;error='account_id is required.'}}
    $sql=@"
SELECT s.id::text AS character_id,s.account_id::text AS account_id,s.character_name AS name,account."user" AS fls_id,
 COALESCE(to_jsonb(b.learned_building_sets),'[]'::jsonb)::text AS sets,
 COALESCE(to_jsonb(b.new_buildable_pieces),'[]'::jsonb)::text AS pieces,
 (a.properties #> '{CustomizationLibraryActorComponent,m_UnlockedCustomizationSerializableList}')::text AS cosmetics
FROM dune.player_state s JOIN dune.accounts account ON account.id=s.account_id
JOIN dune.actors a ON a.id=s.player_pawn_id AND a.owner_account_id=s.account_id
LEFT JOIN dune.building_progression b ON b.character_id=s.id
WHERE s.account_id=$AccountId::bigint;
"@
    $reply=Invoke-DuneSqlQuery -Ip $Ip -Sql $sql -ReadOnly $true -MaxRows 2 -TimeoutSec 30
    if(-not $reply.ok){return @{ok=$false;error="Snapshot read failed: $($reply.error)"}}
    $rows=ConvertTo-DuneRowMaps -Result $reply
    if($rows.Count -ne 1 -or -not $rows[0].name -or -not $rows[0].fls_id){return @{ok=$false;error='Select one active character that has spawned into this world before taking a snapshot.'}}
    try{
        $row=$rows[0]
        $sets=ConvertTo-DuneDockerPurchasedBuilds ($row.sets | ConvertFrom-Json -NoEnumerate -ErrorAction Stop)
        $pieces=ConvertTo-DuneDockerPurchasedBuilds ($row.pieces | ConvertFrom-Json -NoEnumerate -ErrorAction Stop)
        $cosmetics=if($row.cosmetics){$row.cosmetics | ConvertFrom-Json -AsHashtable -Depth 100 -ErrorAction Stop}else{$null}
        if($null -ne $cosmetics -and ($cosmetics -isnot [Collections.IDictionary] -or ($cosmetics.Contains('m_UnlockedCustomizationIds') -and $cosmetics.m_UnlockedCustomizationIds -isnot [Collections.IList]))){throw 'The character cosmetics data is unsupported.'}
        $snapshot=@{name=[string]$row.name;account_id=[string]$row.account_id;character_id=[string]$row.character_id;fls_id=[string]$row.fls_id;
          saved_at=[DateTime]::UtcNow.ToString('o');building_sets=$sets;buildable_pieces=$pieces;cosmetics=$cosmetics}
        $path=Get-DuneDockerFreshStartPath
        $gate=[string]::Intern('DST.Docker.FreshStart.Snapshots')
        [Threading.Monitor]::Enter($gate)
        try{
            $store=Read-DuneDockerFreshStartStore -Path $path
            $store.snapshots=@($store.snapshots | Where-Object {$_.fls_id -cne $snapshot.fls_id})+@($snapshot)
            Save-DuneDockerFreshStartStore -Path $path -Store $store
        }finally{[Threading.Monitor]::Exit($gate)}
        return @{ok=$true;message="Purchase snapshot saved for '$($snapshot.name)'. Delete and recreate the character in-game, then restore onto that account while offline.";name=$snapshot.name;sets=$sets.Count;pieces=$pieces.Count;cosmetics=[bool]$cosmetics}
    }catch{return @{ok=$false;error=$_.Exception.Message}}
}

function Invoke-DuneDockerPlayerRestoreBuilds {
    param([string]$Ip,[string]$Name,[long]$AccountId=0,[bool]$SkipNpe=$false)
    try{
        $path=Get-DuneDockerFreshStartPath
        $gate=[string]::Intern('DST.Docker.FreshStart.Snapshots')
        [Threading.Monitor]::Enter($gate)
        try{
            $store=Read-DuneDockerFreshStartStore -Path $path
            $matches=@($store.snapshots | Where-Object {if($AccountId -gt 0){[string]$_.account_id -ceq [string]$AccountId}else{[string]$_.name -eq $Name}})
            if($matches.Count -ne 1){return @{ok=$false;error='One purchase snapshot for the selected account is required. Take its snapshot before deleting the character.'}}
            $snapshot=$matches[0]
        }finally{[Threading.Monitor]::Exit($gate)}
        $account=0L
        if(-not [long]::TryParse([string]$snapshot.account_id,[ref]$account) -or $account -le 0){throw 'The snapshot account identity is invalid.'}
        $payload=@{fls_id=[string]$snapshot.fls_id;sets=(ConvertTo-DuneDockerPurchasedBuilds $snapshot.building_sets);
          pieces=(ConvertTo-DuneDockerPurchasedBuilds $snapshot.buildable_pieces);cosmetics=$snapshot.cosmetics;nodes=@()}
        if($SkipNpe){
            $payload.nodes=@(Get-DuneNpeCompletionNodes | Select-Object -Unique)
            if($payload.nodes.Count -eq 0){throw 'The tutorial completion catalog is unavailable. Nothing was restored.'}
        }
        $sql=Get-DuneDockerFreshStartRestoreSql -AccountId $account -Payload $payload -SkipNpe $SkipNpe
        $reply=Invoke-DuneSqlQuery -Ip $Ip -Sql $sql -ReadOnly $false -MaxRows 1 -TimeoutSec 60 -Bulk
        if(-not $reply.ok){return @{ok=$false;error="Restore purchases failed: $($reply.error)"}}
        return @{ok=$true;message="Purchase snapshot restored for '$($snapshot.name)'. Current unlocks were preserved. Changes take effect on the next login.";sets=$payload.sets.Count;pieces=$payload.pieces.Count;npe_marked=$SkipNpe}
    }catch{return @{ok=$false;error=$_.Exception.Message}}
}
