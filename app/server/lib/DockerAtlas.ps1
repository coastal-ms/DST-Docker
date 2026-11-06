function Get-DuneDockerAtlasSession {
    $start=[Diagnostics.ProcessStartInfo]::new()
    $start.FileName='python3'
    [void]$start.ArgumentList.Add('/opt/dst/packaging/docker/atlas-service.py')
    [void]$start.ArgumentList.Add([string]$PID)
    $start.UseShellExecute=$false
    $start.RedirectStandardOutput=$true
    $start.RedirectStandardError=$true
    $process=[Diagnostics.Process]::new();$process.StartInfo=$start
    try {
        [void]$process.Start()
        $output=$process.StandardOutput.ReadToEndAsync()
        $errorOutput=$process.StandardError.ReadToEndAsync()
        if(-not $process.WaitForExit(12000)){ $process.Kill($true); throw 'Map service startup timed out.' }
        if($process.ExitCode -ne 0){ throw 'Map service startup failed.' }
        $record=$output.GetAwaiter().GetResult() | ConvertFrom-Json
        $url=ConvertTo-DuneAtlasSessionUrl $record.url
        if(-not $url){return @{available=$false;reasonCode='startup-pending'}}
        return @{available=$true;url=$url;mode='snapshot';hosting='docker'}
    } finally {$process.Dispose()}
}
