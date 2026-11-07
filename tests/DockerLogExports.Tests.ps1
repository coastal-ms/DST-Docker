BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'Commands.ps1'
    Import-DstLib 'DockerRoutes.ps1'
    Import-DstLib 'DockerManager.ps1'
    . (Join-Path (Get-DstRepoRoot) 'app/server/HttpServer.ps1')
    $script:routes=@{}
    function Register-DuneRoute {param($Method,$Path,[switch]$LocalOnly,[switch]$StreamBody,$Handler);$script:routes["$Method $Path"]=@{local=[bool]$LocalOnly;handler=$Handler}}
    function Write-DuneError {param($Response,$Status,$Message)}
    function Write-DuneFile {param($Response,$Path)}
    function Write-DuneJson {param($Response,$Body)}
    . (Join-Path (Get-DstRepoRoot) 'app/server/routes/Docker.ps1')
}
Describe 'Native memory mode request validation' {
    BeforeEach {
        $script:oldBackend=$env:DST_HOSTING_BACKEND;$env:DST_HOSTING_BACKEND='docker'
        Mock Invoke-DuneDockerManager {@{ok=$true;data=@{enabled=$false}}}
        Mock Write-DuneError {}
        Mock Write-DuneJson {}
    }
    AfterEach {$env:DST_HOSTING_BACKEND=$script:oldBackend}
    It 'allows the authenticated owner surface over LAN and retains a typed boolean setter' {
        $route=$script:routes['PUT /api/docker/memory-balancing'];$route.local|Should -BeFalse
        & $route.handler $null $null @{} @{enabled=$false}
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'memory.policy.set' -and $Request.enabled -eq $false}
        Should -Invoke Write-DuneJson -Times 1 -ParameterFilter {$Body.enabled -eq $false}
    }
    It 'rejects a string boolean before touching the manager' {
        & $script:routes['PUT /api/docker/memory-balancing'].handler $null $null @{} @{enabled='false'}
        Should -Invoke Write-DuneError -Times 1 -ParameterFilter {$Status -eq 400}
        Should -Invoke Invoke-DuneDockerManager -Times 0
    }
}
Describe 'Native log download boundary' {
    BeforeEach {
        $script:oldBackend=$env:DST_HOSTING_BACKEND;$env:DST_HOSTING_BACKEND='docker'
        Mock Write-DuneError {}
        Mock Write-DuneFile {}
        Mock Get-Item {@{PSIsContainer=$false;LinkType=$null}}
    }
    AfterEach {$env:DST_HOSTING_BACKEND=$script:oldBackend}
    It 'keeps log commands available through the existing native catalogue' {
        $state=@{hostingBackend='docker';prepared=$true;desiredState='running'}
        foreach($name in @('logs-export','operator-logs-export')){
            (Get-DuneCommandAvailability -Command @{Name=$name} -State $state).available|Should -BeTrue
        }
    }
    It 'allows authenticated owner downloads by IP and restricts paths to fixed export identities' {
        $route=$script:routes['GET /api/docker/log-exports/{id}']
        $route.local|Should -BeFalse
        Test-DunePortalOwnerOnlyPath -Path ('/api/docker/log-exports/'+('a'*32)) -Method GET | Should -BeTrue
        Test-DuneDockerRouteQualified -Method GET -Path ('/api/docker/log-exports/'+('a'*32))|Should -BeTrue
        Test-DuneDockerRouteQualified -Method GET -Path '/api/docker/log-exports/../../secret'|Should -BeFalse
        & $route.handler $null @{Headers=@{}} @{id=('../secret')} $null
        Should -Invoke Write-DuneError -Times 1 -ParameterFilter {$Status -eq 404}
        Should -Invoke Get-Item -Times 0
        Should -Invoke Write-DuneFile -Times 0
    }
    It 'serves only a completed regular archive with an attachment header' {
        $response=@{Headers=@{}}
        & $script:routes['GET /api/docker/log-exports/{id}'].handler $null $response @{id=('a'*32)} $null
        $response.Headers['Content-Disposition']|Should -Match 'attachment;'
        Should -Invoke Write-DuneFile -Times 1 -ParameterFilter {$Path.Replace('\','/') -eq ('/control/log-exports/'+('a'*32)+'.zip')}
    }
    It 'refuses symlinks and expired downloads' -TestCases @(@{item=$null},@{item=@{LinkType='SymbolicLink';PSIsContainer=$false}}) {
        param($item)
        Mock Get-Item {return $item}
        & $script:routes['GET /api/docker/log-exports/{id}'].handler $null @{Headers=@{}} @{id=('a'*32)} $null
        Should -Invoke Write-DuneError -Times 1 -ParameterFilter {$Status -eq 404}
        Should -Invoke Write-DuneFile -Times 0
    }
}
