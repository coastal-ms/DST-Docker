function Get-DuneDockerHostScope {
    param([string]$ConfigurationPath='/data/config/DuneServer/docker-database.json')
    $settings=Get-Content -LiteralPath $ConfigurationPath -Raw | ConvertFrom-Json
    $reply=Invoke-DuneDockerManager -Request @{action='status'}
    if(-not $reply.ok){throw 'Docker database ownership could not be observed.'}
    $metadata=$reply.data
    if($metadata.projectId -notmatch '^[a-f0-9]{32}$' -or $metadata.database.instanceId -notmatch '^[a-f0-9]{64}$' -or
       $settings.host -cne '127.0.0.1' -or $settings.database -cne 'dune' -or $settings.user -cne 'dune' -or
       [int]$settings.port -ne [int]$metadata.database.port){throw 'The configured database does not match the owned Docker world.'}
    $identity=Invoke-DuneSqlQuery -Ip docker -ReadOnly $true -MaxRows 1 -TimeoutSec 15 -Sql @'
SELECT current_database() AS database, current_user AS role,
       (SELECT oid::text FROM pg_database WHERE datname=current_database()) AS oid;
'@
    if(-not $identity.ok){throw 'Docker database identity could not be verified.'}
    $rows=ConvertTo-DuneRowMaps -Result $identity
    if($rows.Count -ne 1 -or $rows[0].database -cne 'dune' -or $rows[0].role -cne 'dune' -or $rows[0].oid -notmatch '^[0-9]+$'){
        throw 'The active connection does not match the owned Docker database.'
    }
    $hash=[Security.Cryptography.SHA256]::Create()
    try {$key=([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes("docker|$($metadata.projectId)|$($metadata.database.instanceId)|$($rows[0].oid)")))).Replace('-','').ToLowerInvariant()}
    finally {$hash.Dispose()}
    return @{key=$key;namespace="docker-$($metadata.projectId)";world=$metadata.projectId}
}

function Invoke-DuneDockerSafetyBackup {
    $scope=Get-DuneDockerHostScope
    $started=Invoke-DuneDockerManager -Request @{action='backups.create'}
    if(-not $started.ok){return @{ok=$false;error=$started.error}}
    $operationId=[string]$started.data.operation.id
    if($operationId -notmatch '^[a-f0-9]{32}$'){return @{ok=$false;error='The fresh backup operation was not identified.'}}
    $deadline=[DateTime]::UtcNow.AddMinutes(12)
    while([DateTime]::UtcNow -lt $deadline){
        $reply=Invoke-DuneDockerManager -Request @{action='status'}
        if(-not $reply.ok){return @{ok=$false;error='The fresh backup could not be observed.'}}
        $metadata=$reply.data
        $backup=@($metadata.backups | Where-Object {$_.operationId -ceq $operationId})
        if($backup.Count -gt 1){return @{ok=$false;error='The fresh backup identity is ambiguous.'}}
        if($metadata.operation.id -ceq $operationId -and $metadata.operation.phase -in @('failed','interrupted')){
            return @{ok=$false;error='The fresh safety backup failed before verification.'}
        }
        if($metadata.operation.id -ceq $operationId -and $metadata.operation.phase -eq 'completed' -and $backup.Count -eq 0){
            return @{ok=$false;error='The current operation produced no fresh safety backup record.'}
        }
        if($backup.Count -eq 1){
            $record=$backup[0]
            if($record.phase -eq 'failed'){return @{ok=$false;error='The fresh safety backup failed verification.'}}
            if($record.phase -eq 'completed'){
                if($record.name -notmatch '^backup-[0-9]+-[a-f0-9]{8}\.dump$' -or [long]$record.bytes -le 1024 -or $record.sha256 -notmatch '^[a-f0-9]{64}$'){
                    return @{ok=$false;error='The fresh safety backup has no verified archive proof.'}
                }
                $current=Get-DuneDockerHostScope
                if($current.key -cne $scope.key){return @{ok=$false;error='The database changed during the safety backup.'}}
                return @{ok=$true;path="dst-$($metadata.projectId)-backups/$($record.name)";bytes=[long]$record.bytes;database_scope=$scope.key;backupId=$record.id;sha256=$record.sha256}
            }
        }
        Start-Sleep -Milliseconds 250
    }
    return @{ok=$false;error='The fresh safety backup did not finish in time. No database write was attempted.'}
}
