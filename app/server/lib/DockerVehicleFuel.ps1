function Invoke-DuneDockerVehicleRefuel {
    param([string]$Ip,[long]$VehicleId)
    if($VehicleId -le 0){return @{ok=$false;error='vehicle_id is required.'}}
    $reply=Invoke-DuneSqlQuery -Ip $Ip -Sql "SELECT a.class::text AS class,a.partition_id::text AS partition_id FROM dune.actors a JOIN dune.vehicles v ON v.id=a.id WHERE a.id=$VehicleId::bigint;" -ReadOnly $true -MaxRows 2 -TimeoutSec 15
    if(-not $reply.ok){return @{ok=$false;error='The selected vehicle could not be read.'}}
    $rows=ConvertTo-DuneRowMaps -Result $reply
    if($rows.Count -ne 1 -or -not $rows[0].class){return @{ok=$false;error='The selected vehicle is unavailable. Refresh the vehicle list.'}}
    $vehicle=$rows[0];$class=[string]$vehicle.class
    $blueprint=$class.Substring($class.LastIndexOf('.')+1).Trim("'")
    $scope=Get-DuneDockerHostScope
    $status=Invoke-DuneDockerManager -Request @{action='status'}
    if(-not $status.ok -or $status.data.projectId -cne $scope.world){return @{ok=$false;error='The vehicle map state could not be verified.'}}
    $games=@($status.data.services | Where-Object {$_.component -match '^game-[1-9][0-9]*$'})
    $partition=0L;[void][long]::TryParse([string]$vehicle.partition_id,[ref]$partition)
    $target=@(if($partition -gt 0){$games | Where-Object {$_.component -ceq "game-$partition"}}else{$games})
    if($target.Count -eq 0 -or @($target | Where-Object {$_.state -notin @('created','exited')}).Count -gt 0){
        return @{ok=$false;error='Stop the vehicle map before refuelling. Saved fuel takes effect when that map starts again.'}
    }
    $sql=@'
DO $dst_fuel$
DECLARE selected dune.actors%ROWTYPE; expected jsonb; touched integer; blueprint text;
BEGIN
 SELECT a.* INTO STRICT selected FROM dune.actors a JOIN dune.vehicles v ON v.id=a.id
 WHERE a.id=__VEHICLE__::bigint FOR UPDATE OF a FOR SHARE OF v;
 IF selected.class::text IS DISTINCT FROM __CLASS__ OR selected.partition_id IS DISTINCT FROM __PARTITION__ THEN
  RAISE EXCEPTION 'The vehicle identity or map changed. Refresh and try again.';
 END IF;
 blueprint:=__BLUEPRINT__;
 IF jsonb_typeof(selected.properties #> ARRAY[blueprint,'m_InitialFuel']) IS DISTINCT FROM 'number' THEN
  RAISE EXCEPTION 'This vehicle has no supported saved fuel value. No changes were made.';
 END IF;
 expected:=jsonb_set(selected.properties,ARRAY[blueprint,'m_InitialFuel'],to_jsonb(1.0::float8),false);
 UPDATE dune.actors SET properties=expected WHERE id=selected.id;
 GET DIAGNOSTICS touched=ROW_COUNT;
 IF touched<>1 OR (SELECT properties FROM dune.actors WHERE id=selected.id) IS DISTINCT FROM expected
 OR (SELECT class FROM dune.actors WHERE id=selected.id) IS DISTINCT FROM selected.class
 OR (SELECT partition_id FROM dune.actors WHERE id=selected.id) IS DISTINCT FROM selected.partition_id THEN
  RAISE EXCEPTION 'The vehicle fuel change could not be verified. No changes were saved.';
 END IF;
END;
$dst_fuel$;
'@
    $partitionSql=if($null -eq $vehicle.partition_id -or [string]$vehicle.partition_id -eq ''){'NULL::bigint'}else{"$partition::bigint"}
    $sql=$sql.Replace('__VEHICLE__',[string]$VehicleId).Replace('__CLASS__',(ConvertTo-DuneDockerPlacementText $class)).Replace('__BLUEPRINT__',(ConvertTo-DuneDockerPlacementText $blueprint)).Replace('__PARTITION__',$partitionSql)
    $result=Invoke-DuneSqlQuery -Ip $Ip -Sql $sql -ReadOnly $false -MaxRows 1 -TimeoutSec 30
    if(-not $result.ok){return @{ok=$false;error="Refuel vehicle failed: $($result.error)"}}
    return @{ok=$true;message="Saved full fuel for vehicle $VehicleId. It takes effect when its map starts again."}
}
