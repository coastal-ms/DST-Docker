function Get-DuneDockerBackupData {
    param([Parameter(Mandatory)][hashtable]$Request)
    $reply=Invoke-DuneDockerManager -Request $Request
    if(-not $reply.ok){throw [string]$reply.error}
    return $reply.data
}

function Get-DuneDockerBackupContext {
    try {
        $state=Get-DuneDockerBackupData -Request @{action='status'}
        if($state.projectId -notmatch '^[a-f0-9]{32}$'){throw 'Complete Docker setup first.'}
        return @{ok=$true;ip='docker';backend='docker'}
    }catch{return @{ok=$false;status=503;message=$_.Exception.Message}}
}

function ConvertTo-DuneDockerBackupJobRow {
    param($Job)
    $at=[DateTimeOffset]::FromUnixTimeSeconds([long]$Job.createdAt)
    return @{namespace='docker';name=[string]$Job.name;startTime=$at.ToString('o');phase=[string]$Job.state;
        nameTimestamp=$at.ToString('o');ageMinutes=([DateTimeOffset]::UtcNow-$at).TotalMinutes;
        ownerKind='Docker';ownerName='';ownerIsController=$false;protected=[bool]$Job.protected}
}

function Get-DuneDockerBackupJobs {
    $data=Get-DuneDockerBackupData -Request @{action='backups.jobs'}
    return @(foreach($job in @($data.jobs)){if($job.state -eq 'exited'){ConvertTo-DuneDockerBackupJobRow $job}})
}

function Remove-DuneDockerBackupJobs {
    param([int]$KeepLast,[int]$KeepDays)
    $data=Get-DuneDockerBackupData -Request @{action='backups.jobs.prune';keepLast=$KeepLast;keepDays=$KeepDays}
    return @{ok=$true;deleted=@(foreach($job in @($data.deleted)){ConvertTo-DuneDockerBackupJobRow $job});
        kept=@(foreach($job in @($data.kept)){ConvertTo-DuneDockerBackupJobRow $job});remaining=@(Get-DuneDockerBackupJobs);
        message='Finished backup helper jobs were removed. Backup files and game storage were preserved.'}
}

function Remove-DuneDockerBackupFiles {
    param([string[]]$Paths)
    $state=Get-DuneDockerBackupData -Request @{action='status'}
    $ids=@(foreach($path in $Paths){
        $match=@($state.backups|Where-Object {('/backups/'+$_.name) -ceq $path -and $_.phase -eq 'completed'})
        if($match.Count -ne 1){throw 'Choose a completed backup from this installation.'}
        $match[0].id
    })
    $data=Get-DuneDockerBackupData -Request @{action='backups.delete';backupIds=$ids}
    return @{ok=$true;pending=$true;operationId=$data.operation.id;deleted=@();failed=@();message='Backup deletion started. History updates after the files are checked and removed.'}
}
function Receive-DuneDockerBackupUpload {
    param([Parameter(Mandatory)][IO.Stream]$Stream,[long]$Length,[bool]$TrustedSource,
          [string]$Directory='/data/cache/backup-transfers')
    if(-not $TrustedSource){throw 'Confirm that this backup comes from a trusted source before importing.'}
    if($Length -lt 5 -or $Length -gt 25GB){throw 'Choose a PostgreSQL custom backup between 5 bytes and 25 GiB.'}
    $existing=Get-Item -LiteralPath $Directory -ErrorAction SilentlyContinue
    if($existing -and (-not $existing.PSIsContainer -or $existing.LinkType)){throw 'Private upload storage needs review.'}
    [void][IO.Directory]::CreateDirectory($Directory)
    if($IsLinux){[IO.File]::SetUnixFileMode($Directory,([IO.UnixFileMode]::UserRead -bor [IO.UnixFileMode]::UserWrite -bor [IO.UnixFileMode]::UserExecute -bor [IO.UnixFileMode]::GroupRead -bor [IO.UnixFileMode]::GroupExecute))}
    if(([IO.DriveInfo]::new($Directory)).AvailableFreeSpace -lt ($Length+512MB)){throw 'The upload cache needs room for the backup plus 512 MiB free.'}
    $id=[guid]::NewGuid().ToString('N');$partial=Join-Path $Directory ($id+'.partial');$target=Join-Path $Directory ($id+'.upload')
    $hash=[Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
    $output=$null
    try{
        $prefix=[byte[]]::new(5);$received=0
        while($received -lt 5){$count=$Stream.Read($prefix,$received,5-$received);if($count -eq 0){throw 'The backup upload ended early.'};$received+=$count}
        if([Text.Encoding]::ASCII.GetString($prefix) -cne 'PGDMP'){throw 'Choose a PostgreSQL custom-format backup, not a SQL script or other file.'}
        $output=[IO.FileStream]::new($partial,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        if($IsLinux){[IO.File]::SetUnixFileMode($partial,([IO.UnixFileMode]::UserRead -bor [IO.UnixFileMode]::UserWrite -bor [IO.UnixFileMode]::GroupRead))}
        $output.Write($prefix,0,5);$hash.AppendData($prefix)
        $buffer=[byte[]]::new(1MB);$total=[long]5
        while($total -lt $Length){
            $count=$Stream.Read($buffer,0,[int][Math]::Min($buffer.Length,$Length-$total))
            if($count -eq 0){throw 'The backup upload ended early. The incomplete copy was discarded.'}
            $output.Write($buffer,0,$count);$hash.AppendData($buffer,0,$count);$total+=$count
        }
        $output.Flush($true);$output.Dispose();$output=$null
        $digest=[Convert]::ToHexString($hash.GetHashAndReset()).ToLowerInvariant()
        [IO.File]::Move($partial,$target,$false)
        return @{uploadId=$id;sha256=$digest;bytes=$total;trustedSource=$true}
    }finally{
        if($output){$output.Dispose()};$hash.Dispose()
        if(Test-Path -LiteralPath $partial){[IO.File]::Delete($partial)}
    }
}

function Remove-DuneDockerBackupUploadCache {
    param([string]$Directory='/data/cache/backup-transfers')
    $root=Get-Item -LiteralPath $Directory -ErrorAction SilentlyContinue
    if(-not $root){return}
    if(-not $root.PSIsContainer -or $root.LinkType){throw 'Private backup upload storage needs review.'}
    $files=@(Get-ChildItem -LiteralPath $Directory -File|Where-Object {$_.Name -cmatch '^[a-f0-9]{32}\.(upload|partial)$' -and -not $_.LinkType})
    if(-not $files.Count){return}
    $state=Get-DuneDockerBackupData -Request @{action='status'}
    foreach($file in $files){
        $entry=@($state.backups|Where-Object {$_.uploadId -ceq $file.BaseName})|Select-Object -First 1
        if($entry -and $entry.phase -in @('completed','failed','deleted')){[IO.File]::Delete($file.FullName)}
        elseif(-not $entry -and $state.operation.phase -ne 'running' -and $file.LastWriteTimeUtc -lt [DateTime]::UtcNow.AddHours(-24)){[IO.File]::Delete($file.FullName)}
    }
}
