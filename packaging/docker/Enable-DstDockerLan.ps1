# Run in administrator Windows PowerShell when WSL uses NAT networking.
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$ListenAddress,
    [ValidateRange(1024,65535)][int]$Port = 8088,
    [ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$Distribution = 'Ubuntu'
)
$ErrorActionPreference = 'Stop'
$taskAddress = $null
if (-not [Net.IPAddress]::TryParse($ListenAddress,[ref]$taskAddress) -or
    $taskAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
    [Net.IPAddress]::IsLoopback($taskAddress) -or $taskAddress.Equals([Net.IPAddress]::Any)) {
    throw 'Choose the Windows machine''s specific LAN IPv4 address.'
}
if (-not (Get-NetIPAddress -AddressFamily IPv4 -IPAddress $ListenAddress -ErrorAction SilentlyContinue)) {
    throw 'The chosen address does not belong to this Windows machine.'
}
$taskRoute = (& wsl.exe --distribution $Distribution --exec ip -4 route get 1.1.1.1) -join ' '
if ($LASTEXITCODE -ne 0 -or $taskRoute -notmatch '\bsrc\s+(\d+\.\d+\.\d+\.\d+)') { throw 'Could not determine the running WSL address.' }
$taskWslAddress = $Matches[1]
$taskRuleName = "DST-Docker-Console-$ListenAddress-$Port"
$taskExisting = @(& netsh.exe interface portproxy show v4tov4) | Where-Object { $_ -match ('^\s*'+[regex]::Escape($ListenAddress)+'\s+'+$Port+'\s+') }
$taskFirewall = Get-NetFirewallRule -Name $taskRuleName -ErrorAction SilentlyContinue
if ($taskFirewall -and $taskFirewall.Group -ne 'DST Docker') { throw 'An unrelated firewall rule uses this name; it was left unchanged.' }
if ($taskExisting -and -not $taskFirewall) { throw 'Another forwarding rule already uses this address and port; it was left unchanged.' }
if ($WhatIfPreference) {
    [void]$PSCmdlet.ShouldProcess("${ListenAddress}:$Port -> ${taskWslAddress}:$Port",'Configure DST console forwarding and a private-LAN firewall rule')
    return
}
$taskPrincipal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script in administrator Windows PowerShell to configure the Windows forwarding and firewall rules.'
}
$taskProbe = [Net.Sockets.TcpClient]::new()
try {
    if (-not $taskProbe.ConnectAsync($taskWslAddress,$Port).Wait(3000)) { throw 'The Docker console is not reachable at the WSL address and port. Start it before configuring LAN access.' }
} finally { $taskProbe.Dispose() }
if ($PSCmdlet.ShouldProcess("${ListenAddress}:$Port -> ${taskWslAddress}:$Port",'Configure DST console LAN access')) {
    & netsh.exe interface portproxy add v4tov4 listenaddress=$ListenAddress listenport=$Port connectaddress=$taskWslAddress connectport=$Port protocol=tcp
    if ($LASTEXITCODE -ne 0) { throw 'Windows rejected the forwarding rule.' }
    if ($taskFirewall) {
        Set-NetFirewallRule -Name $taskRuleName -Enabled True -Profile Private -Action Allow -Direction Inbound -RemoteAddress LocalSubnet
        $taskFirewall | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -LocalAddress $ListenAddress -RemoteAddress LocalSubnet
        $taskFirewall | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -Protocol TCP -LocalPort $Port
    } else {
        New-NetFirewallRule -Name $taskRuleName -DisplayName "DST Docker console ($ListenAddress port $Port)" -Group 'DST Docker' -Direction Inbound -Action Allow -Enabled True -Profile Private -Protocol TCP -LocalAddress $ListenAddress -LocalPort $Port -RemoteAddress LocalSubnet | Out-Null
    }
    $taskObserved = (& netsh.exe interface portproxy show v4tov4) -join "`n"
    if ($taskObserved -notmatch ('(?m)^\s*'+[regex]::Escape($ListenAddress)+'\s+'+$Port+'\s+'+[regex]::Escape($taskWslAddress)+'\s+'+$Port+'\s*$')) { throw 'The forwarding rule could not be verified.' }
    Write-Output "DST console: http://${ListenAddress}:$Port/ (use the authenticated link or your portal login)."
    Write-Output 'If WSL gets a new IP after a shutdown, rerun this command to refresh its forwarding target.'
}
