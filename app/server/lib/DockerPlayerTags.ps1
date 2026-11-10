# Native writes use Funcom's active-character procedure in one verified transaction.
function Invoke-DuneDockerPlayerTags {
    param([string]$Ip,[long]$AccountId,[string[]]$Add,[string[]]$Remove,[switch]$Replace)
    if($AccountId -le 0){return @{ok=$false;error='account_id is required.'}}
    $maximum=if($Replace){64}else{128}
    $clean=@{}
    foreach($key in @('Add','Remove')){
        $values=if($key -eq 'Add'){$Add}else{$Remove}
        $set=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach($value in $values){
            $tag=([string]$value).Trim()
            if(-not $tag -or $tag.Length -gt $maximum -or $tag.Contains([char]0)){
                return @{ok=$false;error="Tags must contain between 1 and $maximum characters."}
            }
            [void]$set.Add($tag)
        }
        $clean[$key]=@($set)
    }
    if(-not $Replace -and $clean.Add.Count -eq 0 -and $clean.Remove.Count -eq 0){return @{ok=$false;error='At least one tag must be added or removed.'}}
    $payload=ConvertTo-Json -InputObject $clean -Compress -Depth 3
    $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($payload))
    $sql=@'
DO $dst_tags$
DECLARE selected dune.encrypted_player_state%ROWTYPE; requested jsonb;
        additions text[]; removals text[]; expected text[]; actual text[];
BEGIN
 SELECT * INTO STRICT selected FROM dune.encrypted_player_state
 WHERE account_id=__ACCOUNT__::bigint AND character_state='Active' FOR UPDATE;
 requested:=convert_from(decode('__PAYLOAD__','base64'),'UTF8')::jsonb;
 SELECT COALESCE(array_agg(value),ARRAY[]::text[]) INTO additions FROM jsonb_array_elements_text(requested->'Add');
 SELECT COALESCE(array_agg(value),ARRAY[]::text[]) INTO removals FROM jsonb_array_elements_text(requested->'Remove');
 __REPLACEMENT__
 SELECT COALESCE(array_agg(tag ORDER BY tag),ARRAY[]::text[]) INTO expected FROM (
  SELECT tag FROM dune.player_tags WHERE character_id=selected.id
  UNION SELECT unnest(additions)
  EXCEPT SELECT unnest(removals)
 ) wanted;
 PERFORM dune.update_player_tags(selected.account_id,additions,removals);
 SELECT COALESCE(array_agg(tag ORDER BY tag),ARRAY[]::text[]) INTO actual FROM dune.player_tags WHERE character_id=selected.id;
 IF actual IS DISTINCT FROM expected THEN
  RAISE EXCEPTION 'The character tag change could not be verified. No tag changes were saved.';
 END IF;
END;
$dst_tags$;
'@
    $replacement=if($Replace){@'
 SELECT COALESCE(array_agg(tag),ARRAY[]::text[]) INTO removals FROM dune.player_tags
 WHERE character_id=selected.id AND NOT(tag=ANY(additions));
'@}else{''}
    $sql=$sql.Replace('__ACCOUNT__',[string]$AccountId).Replace('__PAYLOAD__',$encoded).Replace('__REPLACEMENT__',$replacement)
    $result=Invoke-DuneSqlQuery -Ip $Ip -Sql $sql -ReadOnly $false -MaxRows 1 -TimeoutSec 30
    if(-not $result.ok){return @{ok=$false;error="Update character tags failed: $($result.error)"}}
    if($Replace){return @{ok=$true;message="Tags updated for account $AccountId ($($clean.Add.Count) tag(s)).";tags=$clean.Add}}
    return @{ok=$true;message="Tags updated for account $AccountId (+$($clean.Add.Count) / -$($clean.Remove.Count)).";added=$clean.Add;removed=$clean.Remove}
}
