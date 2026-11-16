BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerRoutes.ps1'
    Import-DstLib 'PlayerAccess.ps1'
    . (Join-Path (Get-DstRepoRoot) 'app/server/HttpServer.ps1')
    function Register-DuneRoute {param($Method,$Path,$Handler);$script:httpsRoutes[$Method+' '+$Path]=$Handler}
    function Write-DuneJson {param($Response,$Body);$script:httpsBody=$Body}
    function Write-DuneError {param($Response,$Status,$Message);$script:httpsError=$Status}
    function Get-DuneDockerConsolePort {return 8088}
    function Invoke-DuneDockerManager {param($Request,[switch]$ProductUpdater);$script:httpsRequest=$Request;$script:httpsUpdater=[bool]$ProductUpdater;return $script:httpsService}
    $script:httpsRoutes=@{}
    . (Join-Path (Get-DstRepoRoot) 'app/server/routes/DockerHttps.ps1')
    $script:httpsBackend=$env:DST_HOSTING_BACKEND
}
AfterAll {$env:DST_HOSTING_BACKEND=$script:httpsBackend}
Describe 'Docker HTTPS Settings API' {
    BeforeEach {
        $env:DST_HOSTING_BACKEND='docker';$script:httpsError=0;$script:httpsRequest=$null;$script:httpsBody=$null
        $script:httpsService=@{ok=$true;data=@{supported=$true;enabled=$false}}
    }
    It 'qualifies only exact settings and public-certificate methods, with Owner and Player boundaries' {
        foreach($method in @('GET','POST')){Test-DuneDockerRouteQualified -Method $method -Path '/api/docker/https'|Should -BeTrue}
        Test-DuneDockerRouteQualified -Method GET -Path '/api/docker/https/certificate'|Should -BeTrue
        foreach($pair in @(@('POST','/api/docker/https/certificate'),@('GET','/api/docker/https/key'),@('DELETE','/api/docker/https'))){Test-DuneDockerRouteQualified -Method $pair[0] -Path $pair[1]|Should -BeFalse}
        foreach($path in @('/api/docker/https','/api/docker/https/certificate')) {
            Test-DunePortalOwnerOnlyPath -Method GET -Path $path|Should -BeTrue
            Get-DunePlayerRoutePolicy -Method GET -Path $path|Should -BeNullOrEmpty
        }
        Test-DunePortalOwnerAccess -AccountMode $true -IsLocalRequest $false -PortalSessionAuth @{ok=$true;account=@{role='admin'}}|Should -BeFalse
        Test-DunePortalOwnerAccess -AccountMode $true -IsLocalRequest $false -PortalSessionAuth @{ok=$true;account=@{role='owner'}}|Should -BeTrue
    }
    It 'uses the fixed host-service status action and server-side console port' {
        & $script:httpsRoutes['GET /api/docker/https'] $null $null $null $null
        $script:httpsRequest.action|Should -Be 'https.status';$script:httpsRequest.port|Should -Be 8088;$script:httpsUpdater|Should -BeTrue
    }
    It 'forwards validated prepare and exact-certificate enable actions' {
        & $script:httpsRoutes['POST /api/docker/https'] $null $null $null @{action='prepare';address='192.0.2.1'}
        $script:httpsRequest.address|Should -Be '192.0.2.1';$script:httpsRequest.action|Should -Be 'https.prepare'
        & $script:httpsRoutes['POST /api/docker/https'] $null $null $null @{action='enable';sha256=('a'*64)}
        $script:httpsRequest.action|Should -Be 'https.enable';$script:httpsRequest.sha256|Should -Be ('a'*64)
    }
    It 'rejects arbitrary ports, paths, commands and unconfirmed certificate identities' -ForEach @(
        @{body=@{action='prepare';address='192.0.2.1';port=443}},
        @{body=@{action='prepare';address='example.com'}},
        @{body=@{action='prepare';address='192.0.2.1;id'}},
        @{body=@{action='enable';sha256='wrong'}},
        @{body=@{action='disable';path='/private/key'}},
        @{body=@{action='exec';command='id'}}
    ) {
        & $script:httpsRoutes['POST /api/docker/https'] $null $null $null $body
        $script:httpsError|Should -Be 400;$script:httpsRequest|Should -BeNullOrEmpty
    }
    It 'downloads only the public certificate with fixed attachment name and no caching' {
        $pem="-----BEGIN CERTIFICATE-----`nfixture`n-----END CERTIFICATE-----"
        $script:httpsService=@{ok=$true;data=@{pem=$pem;sha256=('a'*64)}}
        $stream=[IO.MemoryStream]::new()
        $response=[pscustomobject]@{StatusCode=0;ContentType='';Headers=@{};ContentLength64=0L;OutputStream=$stream}
        & $script:httpsRoutes['GET /api/docker/https/certificate'] $null $response $null $null
        $response.StatusCode|Should -Be 200;$response.Headers['Cache-Control']|Should -Be 'no-store'
        $response.Headers['Content-Disposition']|Should -Be 'attachment; filename="dst-docker-root.crt"'
        [Text.Encoding]::ASCII.GetString($stream.ToArray())|Should -Be $pem
        $script:httpsRequest.action|Should -Be 'https.certificate'
    }
    It 'never exports private key material' {
        $script:httpsService=@{ok=$true;data=@{pem='-----BEGIN PRIVATE KEY-----fixture'}}
        & $script:httpsRoutes['GET /api/docker/https/certificate'] $null $null $null $null
        $script:httpsError|Should -Be 409
    }
    It 'is unavailable for the Windows edition' {
        $env:DST_HOSTING_BACKEND='windows'
        & $script:httpsRoutes['GET /api/docker/https'] $null $null $null $null
        $script:httpsError|Should -Be 404;$script:httpsRequest|Should -BeNullOrEmpty
    }
}
