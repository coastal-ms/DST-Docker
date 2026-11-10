# Shared database semantics, with a native Linux PostgreSQL transport.
function Invoke-DuneDockerSqlRaw {
    param([string]$Sql, [int]$TimeoutSec = 30, [bool]$Csv = $true,
          [bool]$ReadOnly = $true, [switch]$Detailed, [switch]$Structured, [int]$MaxRows=1000)
    $timeout = [Math]::Max(1, [Math]::Min(600, $TimeoutSec))
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = '/opt/dst-python/bin/python3'
    [void]$start.ArgumentList.Add('/opt/dst/packaging/docker/database.py')
    $start.UseShellExecute = $false
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardInputEncoding = [Text.UTF8Encoding]::new($false)
    $start.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
    $start.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    try {
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $payload = @{ sql=$Sql; csv=$Csv; readOnly=$ReadOnly; timeoutSeconds=$timeout; structured=[bool]$Structured; maxRows=$MaxRows } | ConvertTo-Json -Compress
        $process.StandardInput.Write($payload)
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(($timeout + 10) * 1000)) {
            $process.Kill($true)
            throw 'Docker database request timed out.'
        }
        if ($process.ExitCode -ne 0) { throw 'Docker database client failed.' }
        $result = $stdout.GetAwaiter().GetResult() | ConvertFrom-Json -AsHashtable -DateKind String
        if ($Detailed) { return $result }
        if ($result.exitCode -ne 0) { return [string]$result.stderr }
        return [string]$result.stdout
    } finally { $process.Dispose() }
}
