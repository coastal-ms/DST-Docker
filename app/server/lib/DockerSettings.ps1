function Invoke-DuneDockerSettingsReader {
    param([Parameter(Mandatory)][hashtable]$Request)
    $start=[Diagnostics.ProcessStartInfo]::new()
    $start.FileName='python3'
    [void]$start.ArgumentList.Add('/opt/dst/packaging/docker/settings_client.py')
    $start.UseShellExecute=$false
    $start.RedirectStandardInput=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
    $start.StandardInputEncoding=[Text.UTF8Encoding]::new($false)
    $start.StandardOutputEncoding=[Text.UTF8Encoding]::new($false)
    $process=[Diagnostics.Process]::new();$process.StartInfo=$start
    try {
        [void]$process.Start()
        $stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
        $process.StandardInput.Write(($Request|ConvertTo-Json -Compress))
        $process.StandardInput.Close()
        if(-not $process.WaitForExit(20000)){$process.Kill($true);throw 'The server settings read timed out.'}
        if($process.ExitCode -ne 0){throw 'The server settings service is unavailable.'}
        $reply=$stdout.GetAwaiter().GetResult()|ConvertFrom-Json -AsHashtable
        if(-not $reply.ok){throw $reply.error}
        return $reply.data
    } finally {$process.Dispose()}
}

function Read-DuneDockerSettingsFile {
    param([Parameter(Mandatory)][ValidateSet('game','engine','server')][string]$File)
    return Invoke-DuneDockerSettingsReader -Request @{action='read';file=$File}
}

function Write-DuneDockerSettingsFile {
    param([Parameter(Mandatory)][ValidateSet('game','engine','server')][string]$File,
        [Parameter(Mandatory)][AllowEmptyString()][string]$Raw,
        [Parameter(Mandatory)][string]$Revision,[bool]$ExpectedExists=$true,[switch]$Remove)
    $reply=Invoke-DuneDockerManager -Request @{action='settings.write';file=$File;raw=$Raw;revision=$Revision;expectedExists=$ExpectedExists;remove=[bool]$Remove}
    if(-not $reply.ok){throw $reply.error}
    return $reply.data
}

function Get-DuneDockerSettingsContext {
    $reply=Invoke-DuneDockerManager -Request @{action='status'}
    if(-not $reply.ok){return @{ok=$false;status=503;message=$reply.error}}
    if(-not @($reply.data.services|Where-Object {$_.component -eq 'game-1'}).Count){return @{ok=$false;status=503;message='Complete Docker Setup before editing server settings.'}}
    return @{ok=$true;ip='docker';native=$reply.data}
}

function Get-DuneDockerRetailSettingsSnapshot {
    $context=Get-DuneDockerSettingsContext
    if(-not $context.ok){return [ordered]@{available=$false;reason=$context.message;source='funcom-persistent-user-settings';target=@{available=$false}}}
    $current=Read-DuneDockerSettingsFile -File server
    $active=@($context.native.services|Where-Object {$_.component -like 'game-*' -and $_.state -notin @('exited','created')})
    $target=@{available=$true;namespace='docker';battlegroup=$context.native.projectId;pod='';persistentVolumeClaim='';
        mountPath='/srv';mountSubPath='';path='/srv/UserSettings/UserServerCustomSettings.ini';
        gamePath='/home/dune/server/DuneSandbox/Saved/Config/LinuxServer/ServerCustomSettings.ini';
        stopped=($context.native.desiredState -eq 'stopped' -and $active.Count -eq 0);serverPodCount=$active.Count;
        upstreamConfigured=$false;upstreamContent=''}
    return [ordered]@{available=$true;source='funcom-persistent-user-settings';authority='Linux UserSettings/UserServerCustomSettings.ini';
        fileExists=$current.fileExists;raw=$current.raw;fileRaw=$current.raw;revision=$current.revision;fileRevision=$current.revision;
        bytes=$current.bytes;modifiedAt=$current.modifiedAt;fileAuthority=$true;needsMigration=$false;target=$target}
}
