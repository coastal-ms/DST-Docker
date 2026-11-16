BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerRoutes.ps1'
    function Register-DuneRoute {param($Method,$Path,$Handler);$script:updateRoutes[$Method]=$Handler}
    function Write-DuneJson {param($Response,$Body);$script:updateReply=$Body}
    function Write-DuneError {param($Response,$Status,$Message);$script:updateError=$Status}
    function Invoke-DuneDockerManager {param($Request,[switch]$ProductUpdater);$script:updateRequest=$Request;$script:usedUpdater=[bool]$ProductUpdater;return $script:serviceReply}
    $script:updateRoutes=@{}
    . (Join-Path (Get-DstRepoRoot) 'app/server/routes/DockerProductUpdate.ps1')
    $script:previousBackend=$env:DST_HOSTING_BACKEND
}
AfterAll {$env:DST_HOSTING_BACKEND=$script:previousBackend}
Describe 'Docker product update API' {
    BeforeEach {
        $env:DST_HOSTING_BACKEND='docker'
        $script:DuneToolVersion='1.0.12'
        $script:updateReply=$null;$script:updateError=0;$script:updateRequest=$null
        $script:serviceReply=@{ok=$true;data=@{available=$true;currentVersion='old';latestVersion='1.0.13'}}
    }
    It 'qualifies only its fixed GET and POST methods' {
        foreach($method in @('GET','POST')){Test-DuneDockerRouteQualified -Method $method -Path '/api/docker/product-update'|Should -BeTrue}
        foreach($method in @('PUT','DELETE')){Test-DuneDockerRouteQualified -Method $method -Path '/api/docker/product-update'|Should -BeFalse}
        Test-DuneDockerRouteQualified -Method GET -Path '/api/docker/product-update/other'|Should -BeFalse
    }
    It 'compares the running version and forwards force checks to the separate updater' {
        & $script:updateRoutes.GET @{QueryString=@{force='1'}} $null $null $null
        $script:usedUpdater|Should -BeTrue
        $script:updateRequest.force|Should -BeTrue
        $script:updateReply.currentVersion|Should -Be '1.0.12'
    }
    It 'posts only the exact confirmed release' {
        & $script:updateRoutes.POST $null $null $null @{tag='v1.0.13';commit=('a'*40);confirmation='UPDATE DST DOCKER'}
        $script:updateError|Should -Be 0
        $script:updateRequest.action|Should -Be 'install'
        $script:updateRequest.commit|Should -Be ('a'*40)
    }
    It 'rejects unconfirmed or arbitrary update parameters' -ForEach @(
        @{body=@{tag='v1.0.13';commit=('a'*40);confirmation='no'}},
        @{body=@{tag='v1.0.13';commit=('a'*40);confirmation='UPDATE DST DOCKER';prefix='/other'}},
        @{body=@{tag='../other';commit=('a'*40);confirmation='UPDATE DST DOCKER'}}
    ) {
        & $script:updateRoutes.POST $null $null $null $body
        $script:updateError|Should -Be 400
        $script:updateRequest|Should -BeNullOrEmpty
    }
    It 'returns a maintenance refusal without claiming success' {
        $script:serviceReply=@{ok=$false;error='Stop the battlegroup first.'}
        & $script:updateRoutes.POST $null $null $null @{tag='v1.0.13';commit=('a'*40);confirmation='UPDATE DST DOCKER'}
        $script:updateError|Should -Be 409
        $script:updateReply|Should -BeNullOrEmpty
    }
    It 'is unavailable on Windows' {
        $env:DST_HOSTING_BACKEND='windows'
        & $script:updateRoutes.GET $null $null $null $null
        $script:updateError|Should -Be 404
    }
}
