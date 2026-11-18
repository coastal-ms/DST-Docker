function Get-DuneDockerContractPayload {
    param([string[]]$ContractIds,[switch]$Reverse)
    if(-not $ContractIds -or $ContractIds.Count -eq 0){return @{ok=$false;error='contract_ids[] is required.'}}
    _Load-DuneTagsData
    $names=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $tags=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $skills=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $remove=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach($id in $ContractIds){
        $resolved=Resolve-DuneContractTagsForId -ContractId $id -AllowRemovalOnly:(-not $Reverse)
        if(-not $resolved.ok){return @{ok=$false;error=$resolved.error}}
        $canonical=@($script:DuneTagsData.contractTags.Keys | Where-Object {[string]::Equals([string]$_,[string]$resolved.name,[StringComparison]::OrdinalIgnoreCase)})
        if($canonical.Count -ne 1){return @{ok=$false;error='The contract catalog identity is ambiguous.'}}
        $name=[string]$canonical[0]
        [void]$names.Add($name)
        foreach($tag in $script:DuneTagsData.contractTags[$name]){[void]$tags.Add([string]$tag)}
        if($script:DuneTagsData.contractSkillGrants.ContainsKey($name)){
            foreach($skill in $script:DuneTagsData.contractSkillGrants[$name]){[void]$skills.Add([string]$skill)}
        }
        if($script:DuneTagsData.contractRemoveTags.ContainsKey($name)){
            foreach($tag in $script:DuneTagsData.contractRemoveTags[$name]){[void]$remove.Add([string]$tag)}
        }
    }
    $bumps=@()
    if(-not $Reverse){
        $floors=Get-DuneTierBumpFromTags -Tags @($tags)
        $bumps=@(foreach($name in $floors.Keys){@{name=[string]$name;minimum=[int]$floors[$name]}})
    }
    $payload=@{add=@();remove=@();skills=@($skills);bumps=$bumps;
      contracts=@($names);short_names=@($names | ForEach-Object {if($_.StartsWith('DA_CT_',[StringComparison]::OrdinalIgnoreCase)){$_.Substring(6)}else{$_}})}
    if($Reverse){$payload.remove=@($tags)}else{$payload.add=@($tags);$payload.remove=@($remove)}
    return @{ok=$true;payload=$payload}
}

function Invoke-DuneDockerPlayerContracts {
    param([string]$Ip,[long]$AccountId,[string[]]$ContractIds,[switch]$Reverse)
    if($AccountId -le 0){return @{ok=$false;error='account_id is required.'}}
    $resolved=Get-DuneDockerContractPayload -ContractIds $ContractIds -Reverse:$Reverse
    if(-not $resolved.ok){return $resolved}
    $sql=Get-DuneDockerContractSql -AccountId $AccountId -Payload $resolved.payload -Reverse:$Reverse
    $reply=Invoke-DuneSqlQuery -Ip $Ip -Sql $sql -ReadOnly $false -MaxRows 1 -TimeoutSec 60 -Bulk
    if(-not $reply.ok){return @{ok=$false;error="Contract transaction failed: $($reply.error)"}}
    $verb=if($Reverse){'Reversed'}else{'Completed'}
    return @{ok=$true;message="$verb $($resolved.payload.contracts.Count) contract(s). Changes take effect on the next login.";contracts=$resolved.payload.contracts.Count}
}

function Get-DuneDockerContractSql {
    param([long]$AccountId,[hashtable]$Payload,[switch]$Reverse)
    $sql=@'
DO $dst_contracts$
DECLARE selected dune.encrypted_player_state%ROWTYPE; pawn dune.actors%ROWTYPE; controller dune.actors%ROWTYPE;
        skill_entity dune.fgl_entities%ROWTYPE; requested jsonb; additions text[]; removals text[];
        expected_tags text[]; actual_tags text[]; skill text; skill_key text; spent integer;
        modules jsonb; expected_components jsonb; floor_entry jsonb; chosen_faction_id smallint;
        faction_name text; rep integer; component_rep integer; minimum_rep integer;
        faction_root jsonb; faction_array jsonb; entry_count integer; entry_index integer;
        expected_controller jsonb; short_names text[]; expected_pawn jsonb; tracked text;
BEGIN
 requested:=__PAYLOAD__::jsonb;
 SELECT * INTO STRICT selected FROM dune.encrypted_player_state
 WHERE account_id=__ACCOUNT__::bigint AND character_state='Active' FOR UPDATE;
 IF selected.online_status IS DISTINCT FROM 'Offline' THEN RAISE EXCEPTION 'The character must finish logging out and show Offline before changing contracts.'; END IF;
 SELECT * INTO STRICT pawn FROM dune.actors WHERE id=selected.player_pawn_id AND owner_account_id=selected.account_id FOR UPDATE;
 SELECT COALESCE(array_agg(value),ARRAY[]::text[]) INTO additions FROM jsonb_array_elements_text(requested->'add');
 SELECT COALESCE(array_agg(value),ARRAY[]::text[]) INTO removals FROM jsonb_array_elements_text(requested->'remove');
 SELECT COALESCE(array_agg(tag ORDER BY tag),ARRAY[]::text[]) INTO expected_tags FROM (
  SELECT tag FROM dune.player_tags WHERE character_id=selected.id
  UNION SELECT unnest(additions)
  EXCEPT SELECT unnest(removals)
 ) wanted;
 PERFORM dune.update_player_tags(selected.account_id,additions,removals);
 SELECT COALESCE(array_agg(tag ORDER BY tag),ARRAY[]::text[]) INTO actual_tags FROM dune.player_tags WHERE character_id=selected.id;
 IF actual_tags IS DISTINCT FROM expected_tags THEN RAISE EXCEPTION 'The contract tags could not be verified. No changes were saved.'; END IF;
 IF jsonb_array_length(requested->'skills')>0 THEN
  SELECT f.* INTO STRICT skill_entity FROM dune.actor_fgl_entities link JOIN dune.fgl_entities f ON f.entity_id=link.entity_id
  WHERE link.actor_id=pawn.id AND link.slot_name='DuneCharacter' FOR UPDATE OF f FOR SHARE OF link;
  IF EXISTS(SELECT 1 FROM dune.actor_fgl_entities WHERE entity_id=skill_entity.entity_id AND actor_id<>pawn.id) THEN
   RAISE EXCEPTION 'The character skill entity is shared and cannot be safely edited.';
  END IF;
  IF jsonb_typeof(skill_entity.components->'FLevelComponent') IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'The character skill component is unavailable.'; END IF;
  IF jsonb_array_length(skill_entity.components->'FLevelComponent')<2
   OR jsonb_typeof(skill_entity.components #> '{FLevelComponent,1}') IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'The character skill component format is unsupported.'; END IF;
  modules:=COALESCE(skill_entity.components #> '{FLevelComponent,1,ModuleData}','{}'::jsonb);
  IF jsonb_typeof(modules)<>'object' THEN RAISE EXCEPTION 'The character skill module format is unsupported.'; END IF;
  FOR skill IN SELECT jsonb_array_elements_text(requested->'skills') LOOP
   skill_key:='(TagName="'||skill||'")';
   IF modules ? skill_key AND jsonb_typeof(modules->skill_key)<>'object' THEN RAISE EXCEPTION 'The saved skill block format is unsupported.'; END IF;
   spent:=COALESCE((modules->skill_key->>'SkillPointsSpent')::integer,0);
   __SKILL_CHANGE__
  END LOOP;
  expected_components:=jsonb_set(skill_entity.components,'{FLevelComponent,1,ModuleData}',modules,true);
  UPDATE dune.fgl_entities SET components=expected_components WHERE entity_id=skill_entity.entity_id;
  IF NOT EXISTS(SELECT 1 FROM dune.fgl_entities WHERE entity_id=skill_entity.entity_id AND components=expected_components) THEN
   RAISE EXCEPTION 'The contract skill change could not be verified. No changes were saved.';
  END IF;
 END IF;
 __COMPLETE__
END;
$dst_contracts$;
'@
    $skillChange=if($Reverse){'IF spent<=1 THEN modules:=modules-skill_key; END IF;'}else{@'
   IF spent<1 THEN modules:=jsonb_set(modules,ARRAY[skill_key],COALESCE(modules->skill_key,'{}'::jsonb)||jsonb_build_object('SkillPointsSpent',1),true); END IF;
'@}
    $complete=if($Reverse){''}else{Get-DuneDockerContractCompletionSql}
    return $sql.Replace('__ACCOUNT__',[string]$AccountId).Replace('__PAYLOAD__',(ConvertTo-DuneDockerPlacementText (ConvertTo-Json -InputObject $Payload -Depth 20 -Compress))).Replace('__SKILL_CHANGE__',$skillChange).Replace('__COMPLETE__',$complete)
}

function Get-DuneDockerContractCompletionSql {
    return @'
 IF jsonb_array_length(requested->'bumps')>0 THEN
  SELECT * INTO STRICT controller FROM dune.actors WHERE id=selected.player_controller_id AND owner_account_id=selected.account_id FOR UPDATE;
  IF controller.properties IS NOT NULL AND jsonb_typeof(controller.properties)<>'object' THEN RAISE EXCEPTION 'The faction controller properties format is unsupported.'; END IF;
  expected_controller:=COALESCE(controller.properties,'{}'::jsonb);
  faction_root:=COALESCE(expected_controller->'FactionPlayerComponent','{}'::jsonb);
  IF jsonb_typeof(faction_root)<>'object' THEN RAISE EXCEPTION 'The faction component format is unsupported.'; END IF;
  faction_array:=COALESCE(faction_root->'m_FactionDataArray','[]'::jsonb);
  IF jsonb_typeof(faction_array)<>'array' THEN RAISE EXCEPTION 'The faction standing list format is unsupported.'; END IF;
  FOR floor_entry IN SELECT jsonb_array_elements(requested->'bumps') LOOP
   faction_name:=floor_entry->>'name';minimum_rep:=(floor_entry->>'minimum')::integer;
   SELECT id INTO STRICT chosen_faction_id FROM dune.factions WHERE name=faction_name;
   SELECT count(*)::integer,min(ordinality)::integer-1 INTO entry_count,entry_index
    FROM jsonb_array_elements(faction_array) WITH ORDINALITY WHERE value #>> '{Faction,Name}'=faction_name;
   IF entry_count>1 THEN RAISE EXCEPTION 'The faction standing list is ambiguous.'; END IF;
   component_rep:=COALESCE((faction_array->entry_index->>'ReputationAmount')::integer,0);
   SELECT r.reputation_amount INTO rep FROM dune.player_faction_reputation r WHERE r.actor_id=controller.id AND r.faction_id=chosen_faction_id FOR UPDATE;
   rep:=GREATEST(COALESCE(rep,0),component_rep,minimum_rep);
   PERFORM dune.set_player_faction_reputation(controller.id,chosen_faction_id,rep);
   IF entry_count=0 THEN faction_array:=faction_array||jsonb_build_array(jsonb_build_object('Faction',jsonb_build_object('Name',faction_name),'timestamp',extract(epoch FROM now()),'ReputationAmount',rep));
   ELSE faction_array:=jsonb_set(faction_array,ARRAY[entry_index::text,'ReputationAmount'],to_jsonb(rep),true); END IF;
   IF NOT EXISTS(SELECT 1 FROM dune.player_faction_reputation r WHERE r.actor_id=controller.id AND r.faction_id=chosen_faction_id AND reputation_amount=rep) THEN
    RAISE EXCEPTION 'The contract reputation could not be verified. No changes were saved.';
   END IF;
  END LOOP;
  expected_controller:=expected_controller||jsonb_build_object('FactionPlayerComponent',faction_root||jsonb_build_object('m_FactionDataArray',faction_array));
  UPDATE dune.actors SET properties=expected_controller WHERE id=controller.id;
  IF NOT EXISTS(SELECT 1 FROM dune.actors WHERE id=controller.id AND properties=expected_controller) THEN
   RAISE EXCEPTION 'The contract faction component could not be verified. No changes were saved.';
  END IF;
 END IF;
 SELECT COALESCE(array_agg(value),ARRAY[]::text[]) INTO short_names FROM jsonb_array_elements_text(requested->'short_names');
 PERFORM 1 FROM dune.inventories WHERE actor_id=pawn.id AND inventory_type=29 FOR SHARE;
 DELETE FROM dune.items i USING dune.inventories inv WHERE inv.id=i.inventory_id AND inv.actor_id=pawn.id AND inv.inventory_type=29
  AND i.template_id='ContractItem' AND i.stats #>> '{FContractItemStats,1,ContractName,Name}'=ANY(short_names);
 IF EXISTS(SELECT 1 FROM dune.items i JOIN dune.inventories inv ON inv.id=i.inventory_id WHERE inv.actor_id=pawn.id AND inv.inventory_type=29
  AND i.template_id='ContractItem' AND i.stats #>> '{FContractItemStats,1,ContractName,Name}'=ANY(short_names)) THEN
  RAISE EXCEPTION 'The completed contract items could not be verified. No changes were saved.';
 END IF;
 SELECT properties INTO expected_pawn FROM dune.actors WHERE id=pawn.id;
 tracked:=expected_pawn #>> '{ContractsCoordinatorComponent,m_TrackedContractItemUid}';
 IF tracked IS NOT NULL AND tracked<>'!!itm#0' AND NOT EXISTS(SELECT 1 FROM dune.items WHERE '!!itm#'||id::text=tracked) THEN
  expected_pawn:=jsonb_set(expected_pawn,'{ContractsCoordinatorComponent,m_TrackedContractItemUid}',to_jsonb('!!itm#0'::text),false);
  UPDATE dune.actors SET properties=expected_pawn WHERE id=pawn.id;
  IF NOT EXISTS(SELECT 1 FROM dune.actors WHERE id=pawn.id AND properties=expected_pawn) THEN
   RAISE EXCEPTION 'The completed contract card cleanup could not be verified. No changes were saved.';
  END IF;
 END IF;
'@
}
