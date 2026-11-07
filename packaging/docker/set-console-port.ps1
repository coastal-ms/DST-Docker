param([Parameter(Mandatory)][ValidateRange(1024,65535)][int]$Port)
$ErrorActionPreference='Stop'
. /opt/dst/app/server/lib/DockerConsole.ps1
Set-DuneDockerConsolePort -Port $Port
Write-Output "Docker console port saved: $Port. Restart the console to use it."
