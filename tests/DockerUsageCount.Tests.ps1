BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'Config.ps1'
    Import-DstLib 'DockerRoutes.ps1'
    function Register-DuneRoute {param($Method,$Path,$Handler);$script:usageRoutes[$Method]=$Handler}
    function Write-DuneJson {param($Response,$Body);$script:usageReply=$Body}
    function Write-DuneError {param($Response,$Status,$Message);$script:usageError=$Status}
    function Invoke-WithDuneLock {param($Name,$Script);& $Script}
    $script:usageRoutes=@{}
    . (Join-Path (Get-DstRepoRoot) 'app/server/routes/DockerUsageCount.ps1')
    $script:previousBackend=$env:DST_HOSTING_BACKEND
}
AfterAll {$env:DST_HOSTING_BACKEND=$script:previousBackend}
Describe 'Docker anonymous count preference' {
    BeforeEach {
        $env:DST_HOSTING_BACKEND='docker'
        $script:DuneConfigFile=Join-Path $TestDrive (([guid]::NewGuid().ToString('N'))+'.config')
        $script:usageReply=$null;$script:usageError=0
    }
    It 'qualifies only the two preference methods without exposing host configuration' {
        foreach($method in @('GET','PUT')){Test-DuneDockerRouteQualified -Method $method -Path '/api/docker/usage-count'|Should -BeTrue}
        foreach($method in @('POST','DELETE')){Test-DuneDockerRouteQualified -Method $method -Path '/api/docker/usage-count'|Should -BeFalse}
        Test-DuneDockerRouteQualified -Method GET -Path '/api/docker/usage-count/extra'|Should -BeFalse
        Test-DuneDockerRouteQualified -Method GET -Path '/api/config'|Should -BeFalse
    }
    It 'reads an unset preference without exposing any other configuration' {
        & $script:usageRoutes.GET $null $null $null $null
        $script:usageReply.values.AnonymousUsageEnabled|Should -Be ''
        @($script:usageReply.values.Keys).Count|Should -Be 1
    }
    It 'saves opt out and opt in while preserving unrelated configuration' {
        Set-Content $script:DuneConfigFile 'DdnsHostname=keep.example.test'
        foreach($value in @('false','true')) {
            & $script:usageRoutes.PUT $null $null $null @{values=@{AnonymousUsageEnabled=$value}}
            $script:usageReply.ok|Should -BeTrue
            & $script:usageRoutes.GET $null $null $null $null
            $script:usageReply.values.AnonymousUsageEnabled|Should -Be $value
            (Read-DuneConfigRaw).DdnsHostname|Should -Be 'keep.example.test'
        }
    }
    It 'rejects arbitrary configuration keys and invalid values' -ForEach @(
        @{body=@{values=@{AnonymousUsageEnabled='false';SshKey='other'}}},
        @{body=@{values=@{AnonymousUsageEnabled=12}}},
        @{body=@{values=@{AnonymousUsageEnabled='yes'}}},
        @{body=@{values=@{AnonymousUsageEnabled='true'};extra='no'}}
    ) {
        & $script:usageRoutes.PUT $null $null $null $body
        $script:usageError|Should -Be 400
        Test-Path $script:DuneConfigFile|Should -BeFalse
    }
    It 'does not expose the Docker setting in another edition' {
        $env:DST_HOSTING_BACKEND=''
        & $script:usageRoutes.GET $null $null $null $null
        $script:usageError|Should -Be 404
    }
}
