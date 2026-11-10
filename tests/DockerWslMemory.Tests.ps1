BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    $script:handlers=@{}
    function Register-DuneRoute {param($Method,$Path,$Handler,[switch]$StreamBody);$script:handlers["$Method $Path"]=$Handler}
    . (Join-Path (Get-DstRepoRoot) 'app/server/routes/Docker.ps1')
    function global:Invoke-DuneDockerManager {param($Request,[switch]$HostSession)}
    function global:Write-DuneJson {param($Response,$Body)}
    function global:Write-DuneError {param($Response,$Status,$Message)}
}
Describe 'WSL memory settings transport' {
    BeforeEach {
        Mock Invoke-DuneDockerManager {@{ok=$true;data=@{platform='wsl';available=$true}}}
        Mock Write-DuneJson {}
        Mock Write-DuneError {}
    }
    It 'reads memory details through the existing Owner host route' {
        & $script:handlers['GET /api/docker/host'] @{QueryString=@{detail='memory'}} $null @{} @{}
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$HostSession -and $Request.action -ceq 'memory.get'}
        Should -Invoke Write-DuneJson -Times 1
    }
    It 'sends a custom limit without sending a shutdown request' {
        & $script:handlers['POST /api/docker/host'] $null $null @{} @{action='memory.set';memoryGiB=24}
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$HostSession -and $Request.action -ceq 'memory.set' -and $Request.memoryGiB -eq 24}
        Should -Invoke Write-DuneError -Times 0
    }
    It 'preserves an explicit null for restoring the WSL default' {
        & $script:handlers['POST /api/docker/host'] $null $null @{} @{action='memory.set';memoryGiB=$null}
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -ceq 'memory.set' -and $null -eq $Request.memoryGiB}
    }
    It 'rejects missing string and boolean limits before invoking the host' {
        foreach($body in @(@{action='memory.set'},@{action='memory.set';memoryGiB='24'},@{action='memory.set';memoryGiB=$true})) {
            & $script:handlers['POST /api/docker/host'] $null $null @{} $body
        }
        Should -Invoke Invoke-DuneDockerManager -Times 0
        Should -Invoke Write-DuneError -Times 3 -ParameterFilter {$Status -eq 409}
    }
}
