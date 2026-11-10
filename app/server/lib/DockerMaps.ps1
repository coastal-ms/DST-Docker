function Get-DuneDockerDeepDesertInstances {
    $reply=Invoke-DuneDockerManager -Request @{action='status'}
    if(-not $reply.ok){throw $reply.error}
    $metadata=$reply.data
    $games=@($metadata.plan.games | Where-Object {$_.map -ceq 'DeepDesert_1'})
    $lookup=@{}
    $active=@($metadata.services|Where-Object {$_.state -in @('running','restarting') -and $_.component -in @($games|ForEach-Object {"game-$($_.partition)"})})
    # A stopped world has no active instances to resolve. Its saved partition
    # selections can be reviewed without waking the database or inventing IDs.
    if($active.Count -gt 0){
        $dimensions=Invoke-DuneSqlQuery -Ip docker -ReadOnly $true -Sql "SELECT partition_id, dimension_index FROM dune.world_partition WHERE map='DeepDesert_1';"
        if(-not $dimensions.ok){throw 'Deep Desert partition identities could not be verified.'}
        foreach($row in (ConvertTo-DuneRowMaps -Result $dimensions)){$lookup[[int]$row.partition_id]=[int]$row.dimension_index}
    }
    $instances=@(foreach($game in $games){
        $entry=@($metadata.services|Where-Object {$_.component -eq "game-$($game.partition)"}) | Select-Object -First 1
        if(-not $entry -or $entry.state -notin @('running','restarting')){continue}
        if(-not $lookup.ContainsKey([int]$game.partition)){throw 'An active Deep Desert partition no longer matches the game database.'}
        [pscustomobject]@{Map='DeepDesert_1';PartitionId=[int]$game.partition;Dimension=$lookup[[int]$game.partition];
            Phase=$(if($entry.state -eq 'restarting'){'Restarting'}else{'Running'});Ready=($entry.gameReady -eq $true);
            GamePort=[int]$game.gamePort;ServerDisplayName=$null}
    })
    return @{Ns='docker';Name=$metadata.projectId;Title=$metadata.profile.name;
        ConfiguredPartitionIds=@($games|ForEach-Object {[int]$_.partition}|Sort-Object -Unique);Instances=$instances}
}

function Get-DuneDockerMapDefinition {
    param([string]$Key)
    $definitions=@{
        deepdesert=@{map='DeepDesert_1';label='Deep Desert'}
        arakeen=@{map='SH_Arrakeen';label='Arrakeen'}
        harkovillage=@{map='SH_HarkoVillage';label='Harko Village'}
        survival=@{map='Survival_1';label='Hagga Basin'}
        overmap=@{map='Overmap';label='Overmap'}
    }
    if(-not $definitions.ContainsKey($Key)){throw "Unknown map: $Key"}
    return $definitions[$Key]
}

function Get-DuneDockerMapState {
    param([string]$Key)
    $definition=Get-DuneDockerMapDefinition $Key
    $reply=Invoke-DuneDockerManager -Request @{action='status'}
    if(-not $reply.ok){return @{ok=$false;status=503;message=$reply.error}}
    $metadata=$reply.data
    $game=@($metadata.plan.games | Where-Object {$_.map -eq $definition.map})[0]
    if(-not $game){return @{ok=$false;status=404;message='Map is not in this world.'}}
    $entry=@($metadata.services | Where-Object {$_.component -eq "game-$($game.partition)"})[0]
    $active=$entry.state -eq 'running'
    $ready=$active -and $entry.gameReady -eq $true
    $target=$entry.desiredState -eq 'running'
    $players=if($active){$entry.players}else{0}
    $playerIds=@();$playersError=$null
    if($active -and $entry.gameServerId){
        $observed=_Get-DuneMapPlayersOnline -Ip docker -ServerGuids @([string]$entry.gameServerId)
        if($observed.count -lt 0){$players=$null;$playersError=$observed.error}
        else {
            $playerIds=@($observed.ids)
            $players=if($null -eq $players){$observed.count}else{[Math]::Max([int]$players,[int]$observed.count)}
            if($playerIds.Count -ne $players){$playersError='Player identities are still catching up with the live server count.'}
        }
    }
    return @{ok=$true;key=$Key;label=$definition.label;present=$true;setCount=1;totalReplicas=[int]$target;
        hasDisabledPart=$false;running=[bool]$ready;activeInstances=[int]$active;readyInstances=[int]$ready;
        targetInstances=[int]$target;playersOnline=$players;playerIds=$playerIds;playersError=$playersError;
        partition=[int]$game.partition;sets=@(@{idx=0;map=$definition.map;replicas=[int]$target;dedicatedScaling=$false;partitionCount=1})}
}

function Invoke-DuneDockerMapControl {
    param([string]$Key,[bool]$Running,[switch]$Force)
    $current=Get-DuneDockerMapState $Key
    if(-not $current.ok){return $current}
    if(-not $Running -and $current.activeInstances -gt 0 -and ($null -eq $current.playersOnline -or $current.playersOnline -gt 0) -and -not $Force){
        return @{ok=$false;status=409;requiresConfirmation=$true;playersOnline=$current.playersOnline;message='Players may be connected to this map. Stop it anyway?'}
    }
    $action=if($Running){'maps.start'}else{'maps.stop'}
    $reply=Invoke-DuneDockerManager -Request @{action=$action;partition=$current.partition;force=[bool]$Force}
    if(-not $reply.ok){return @{ok=$false;status=409;message=$reply.error}}
    return @{ok=$true;key=$Key;label=$current.label;operationId=$reply.data.operation.id;message='Map operation started.'}
}

function Invoke-DuneDockerMapRestart {
    param([string]$Key)
    $current=Get-DuneDockerMapState -Key $Key
    if(-not $current.ok){return $current}
    if($current.activeInstances -eq 0){return @{ok=$true;key=$Key;noop=$true;podsFound=0;podsDeleted=0;message="No running $($current.label) server found — nothing to restart."}}
    # The shared HTTP handler has already enforced the disruptive-action guard.
    $reply=Invoke-DuneDockerManager -Request @{action='maps.restart';partition=$current.partition;force=$true}
    if(-not $reply.ok){return @{ok=$false;status=409;message=$reply.error}}
    return @{ok=$true;key=$Key;label=$current.label;podsFound=$current.activeInstances;podsDeleted=0;operationId=$reply.data.operation.id;message="Restarting $($current.label). Its saved spin-up policy is unchanged."}
}
