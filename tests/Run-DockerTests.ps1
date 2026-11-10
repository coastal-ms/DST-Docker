[CmdletBinding()]
param([switch]$CI)
$ErrorActionPreference='Stop'
if(-not $IsLinux){throw 'Docker backend tests must run with PowerShell on Linux.'}
$scratch=Join-Path ([IO.Path]::GetTempPath()) ('dst-docker-pester-'+[guid]::NewGuid().ToString('N'))
$previousAppData=$env:APPDATA
$previousLocalAppData=$env:LOCALAPPDATA
try {
    $env:APPDATA=Join-Path $scratch 'config'
    $env:LOCALAPPDATA=Join-Path $scratch 'local'
    [void][IO.Directory]::CreateDirectory($env:APPDATA)
    [void][IO.Directory]::CreateDirectory($env:LOCALAPPDATA)
    $tests=@(Get-ChildItem $PSScriptRoot -Filter 'Docker*.Tests.ps1' -File|Sort-Object Name)
    if(-not $tests.Count){throw 'No Docker Pester tests were discovered.'}
    & (Join-Path $PSScriptRoot 'Run-Tests.ps1') -Path $tests.FullName -CI:$CI
    exit $LASTEXITCODE
} finally {
    $env:APPDATA=$previousAppData
    $env:LOCALAPPDATA=$previousLocalAppData
}
