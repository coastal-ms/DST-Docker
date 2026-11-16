BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerManager.ps1'
    Import-DstLib 'PublicIp.ps1'
    $script:handlers=@{}
    function Register-DuneRoute {param($Method,$Path,$Handler);$script:handlers["$Method $Path"]=$Handler}
    . (Join-Path (Get-DstRepoRoot) 'app/server/routes/Docker.ps1')
    function global:Write-DuneJson {param($Response,$Body)}
    function global:Write-DuneError {param($Response,$Status,$Message)}
}
Describe 'Private address discovery before the desktop host session starts' {
    BeforeEach {
        $script:oldBackend=$env:DST_HOSTING_BACKEND;$env:DST_HOSTING_BACKEND='docker'
        $script:localIp='172.25.199.100'
        Mock Test-DuneDockerWslHost {$true}
        Mock Invoke-DuneDockerManager {@{ok=$false;error='Host socket unavailable'}}
        Mock Get-DuneDockerNetworkAddresses {
            param([switch]$LocalOnly)
            @{dockerIp=$(if($LocalOnly){$script:localIp}else{'192.168.1.99'});networkingMode='unknown'}
        }
        Mock Write-DuneJson {}
        Mock Write-DuneError {}
    }
    AfterEach {$env:DST_HOSTING_BACKEND=$script:oldBackend}
    It 'returns the current private host route instead of failing or using stale cached data' {
        & $script:handlers['GET /api/docker/network'] ([pscustomobject]@{QueryString=@{}}) $null @{} $null
        Should -Invoke Write-DuneJson -Times 1 -ParameterFilter {$Body.dockerIp -eq '172.25.199.100'}
        Should -Invoke Get-DuneDockerNetworkAddresses -Times 1 -ParameterFilter {$LocalOnly}
        Should -Invoke Write-DuneError -Times 0
    }
    It 'accepts a private host address <address>' -ForEach @(@{address='10.0.0.2'},@{address='172.16.0.2'},@{address='172.31.255.2'},@{address='192.168.23.219'}) {
        $script:localIp=$address
        & $script:handlers['GET /api/docker/network'] ([pscustomobject]@{QueryString=@{}}) $null @{} $null
        Should -Invoke Write-DuneJson -Times 1
        Should -Invoke Write-DuneError -Times 0
    }
    It 'does not advertise an unusable or public address <address>' -ForEach @(@{address=''},@{address='0.0.0.0'},@{address='127.0.0.1'},@{address='169.254.1.2'},@{address='172.15.1.2'},@{address='172.32.1.2'},@{address='8.8.8.8'},@{address='224.0.0.1'},@{address='not-an-ip'},@{address='::1'}) {
        $script:localIp=$address
        & $script:handlers['GET /api/docker/network'] ([pscustomobject]@{QueryString=@{}}) $null @{} $null
        Should -Invoke Write-DuneError -Times 1 -ParameterFilter {$Status -eq 503}
        Should -Invoke Write-DuneJson -Times 0
    }
    It 'still requires the real host session for a public loopback-status request' {
        & $script:handlers['GET /api/docker/network'] ([pscustomobject]@{QueryString=@{publicIp='8.8.8.8'}}) $null @{} $null
        Should -Invoke Write-DuneError -Times 1 -ParameterFilter {$Status -eq 503}
        Should -Invoke Write-DuneJson -Times 0
    }
    It 'prefers the active host session network information when available' {
        Mock Invoke-DuneDockerManager {@{ok=$true;data=@{dockerIp='192.168.23.220';networkingMode='bridged';routerForwardIp='192.168.23.220'}}}
        & $script:handlers['GET /api/docker/network'] ([pscustomobject]@{QueryString=@{}}) $null @{} $null
        Should -Invoke Write-DuneJson -Times 1 -ParameterFilter {$Body.dockerIp -eq '192.168.23.220' -and $Body.networkingMode -eq 'bridged'}
        Should -Invoke Get-DuneDockerNetworkAddresses -Times 0 -ParameterFilter {$LocalOnly}
    }
}
