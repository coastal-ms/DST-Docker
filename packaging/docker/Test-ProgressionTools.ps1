. /qualification-base.ps1 -InitializeOnly
. /opt/dst/app/server/lib/TestingStations.ps1
$controller=[long]$player.controller_id

$trainer=Invoke-DunePlayerUnlockTrainer -Ip docker -AccountId $account -Job 'Swordmaster'
Assert-Ok $trainer 'Trainer unlock'
$job=Invoke-DunePlayerGrantJobSkills -Ip docker -AccountId $account -Job 'Mentat'
Assert-Ok $job 'Job skill unlock'
$reset=Invoke-DunePlayerResetJobSkills -Ip docker -AccountId $account -Job 'Mentat'
Assert-Ok $reset 'Job skill reset'
$starter=Invoke-DunePlayerSetStarterClass -Ip docker -AccountId $account -Job 'BeneGesserit'
Assert-Ok $starter 'Starter class'
$checks.Add('Trainer unlock, job skills, job reset and starter class run against native PostgreSQL')

$skills=Invoke-DunePlayerGrantAllSkills -Ip docker -AccountId $account
Assert-Ok $skills 'Enable All Skills'
$points=Invoke-DuneSqlQuery -Ip docker -ReadOnly $true -Sql @"
SELECT (fe.components #>> '{FLevelComponent,1,UnspentSkillPoints}')::integer AS points,
       (a.properties #>> '{TechKnowledgePlayerComponent,m_TechKnowledgePoints}')::integer AS intel
FROM dune.actors a JOIN dune.actor_fgl_entities afe ON afe.actor_id=a.id AND afe.slot_name='DuneCharacter'
JOIN dune.fgl_entities fe ON fe.entity_id=afe.entity_id WHERE a.id=$pawn;
"@
Assert-Ok $points 'Skill grant balances'
$balances=@(ConvertTo-DuneRowMaps -Result $points)[0]
if([int]$balances.points -lt 20 -or [int]$balances.intel -lt 100){throw 'Skill grant did not establish its documented point/Intel buffers.'}
$checks.Add('Enable All Skills writes the skill-point and Intel buffers')

$stationSql=Get-DuneTestingStationUnlockSql -PawnId $pawn -ControllerId $controller -AccountId $account -Station 'all'
$stations=Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -MaxRows 1 -Sql $stationSql
Assert-Ok $stations 'Testing Stations transaction'
if([int]@(ConvertTo-DuneRowMaps -Result $stations)[0].selected -ne 6){throw 'All six station difficulties were not verified.'}
$again=Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -MaxRows 1 -Sql $stationSql
Assert-Ok $again 'Repeated station unlock'
if([int]@(ConvertTo-DuneRowMaps -Result $again)[0].added -ne 0){throw 'Repeated station unlock duplicated completion records.'}
$checks.Add('Testing Station transaction verifies all six difficulties and is idempotent')

$catalog=Get-Content -LiteralPath (Get-DuneSoloDataFilePath -Name 'codex-catalog.json') -Raw | ConvertFrom-Json
$fragment=$catalog.fragments[0]
$ids=@(@($fragment.id)+@($fragment.ancestors) | Sort-Object -Unique)
$requiredArray=ConvertTo-DunePgTextArray -Values $ids
$seed=Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -Sql @"
INSERT INTO dune.journey_story_node(character_id,story_node_id,has_pending_reward,complete_condition_state,reveal_condition_state,fail_condition_state,metadata_state,reset_group)
SELECT ps.id,node,false,'false'::jsonb,'false'::jsonb,'{}'::jsonb,'{}'::jsonb,'Default'::dune.JourneyStoryResetGroup
FROM dune.player_state ps CROSS JOIN unnest($requiredArray) node
WHERE ps.account_id=$account AND NOT EXISTS (SELECT 1 FROM dune.journey_story_node saved WHERE saved.character_id=ps.id AND saved.story_node_id=node);
"@
Assert-Ok $seed 'Restored-copy Codex fixture'
$codexSql=Get-DuneCodexGrantSql -AccountId $account -Ids @($fragment.id)
$grant=Invoke-DuneSqlQuery -Ip docker -ReadOnly $false -MaxRows 1 -Sql $codexSql
Assert-Ok $grant 'Codex transaction'
$ownership=Get-DunePlayerCodexLive -Ip docker -AccountId $account
Assert-Ok $ownership 'Codex readback'
$found=$false
foreach($entry in $ownership.fragments){if($entry.id -ceq $fragment.id -and $entry.owned -and $entry.revealed){$found=$true}}
if(-not $found){throw 'Granted Codex fragment did not become owned and visible.'}
$checks.Add('Codex transaction and readback agree on ownership and revealed ancestors')

@{ok=$true;scope='Isolated restored-copy database; shared safety backup qualified independently';checks=@($checks)} | ConvertTo-Json -Depth 4
