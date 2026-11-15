[CmdletBinding()]
param(
    [switch]$ReportThisInstallation,
    [string]$ConfigPath,
    [ValidateSet('windows','docker')][string]$Edition = 'windows',
    [string]$Version = 'unknown'
)
$ErrorActionPreference = 'Stop'
$localReportStatus = $null
$library = Join-Path $PSScriptRoot '../lib/UsageCount.ps1'
if ($ReportThisInstallation) {
    if (-not $ConfigPath) { throw 'Specify the installed DST config file with -ConfigPath. The saved sharing choice is always respected.' }
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { throw 'The installed DST config file was not found.' }
    . $library
    $dataRoot = Join-Path (Split-Path -Parent ([IO.Path]::GetFullPath($ConfigPath))) 'usage-count'
    # This bypasses timing only. It cannot enable sharing or alter the identity.
    Invoke-DuneUsageCountTick -ConfigPath $ConfigPath -DataRoot $dataRoot -Edition $Edition -Version $Version -Force
    $status = Read-DuneUsageJson (Join-Path $dataRoot 'status.json')
    $localReportStatus = if (-not (Test-DuneUsageCountEnabled $ConfigPath)) { 'Sharing disabled' }
        elseif ($status.error) { 'Report unavailable; displaying latest received counts' } else { 'Report refreshed' }
}
$nonce = [guid]::NewGuid().ToString('N')
$counts = Invoke-RestMethod -Uri ('https://duneservertool.com/api/usage.php?refresh=' + $nonce) `
    -Headers @{ 'Cache-Control' = 'no-cache'; Pragma = 'no-cache' } -TimeoutSec 10
$invalidCounts = @($counts.windows, $counts.docker, $counts.total) | Where-Object {
    ($_ -isnot [int] -and $_ -isnot [long]) -or $_ -lt 0
}
if ($counts.protocol -ne 1 -or $counts.windowHours -ne 24 -or @($invalidCounts).Count -gt 0 -or
    $counts.total -ne ($counts.windows + $counts.docker)) {
    throw 'The count service did not return a valid current snapshot.'
}
[pscustomobject]@{
    RefreshedUTC = [DateTimeOffset]::UtcNow.ToString('o')
    'DST for Windows / Solo' = $counts.windows
    'DST Docker' = $counts.docker
    WindowHours = 24
    LocalReport = $localReportStatus
}
