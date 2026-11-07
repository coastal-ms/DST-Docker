BeforeAll {
    . "$PSScriptRoot\_TestHelpers.ps1"
    Import-DstLib 'PlatformRuntime.ps1'
    Import-DstLib 'PlatformCache.ps1'
    Import-DstLib 'DockerRoutes.ps1'
    . (Join-Path (Get-DstRepoRoot) 'app/server/HttpServer.ps1')
    function global:Get-DuneApiCursorSecret {}
}
Describe 'Qualified Docker derived cache' {
    BeforeEach { $script:previousBackend=$env:DST_HOSTING_BACKEND }
    AfterEach { $env:DST_HOSTING_BACKEND=$script:previousBackend }
    It 'adds Linux cache support only to the packaged Docker backend' {
        $env:DST_HOSTING_BACKEND=''
        Test-DunePlatformLiveCacheSupported -RuntimePlatform linux | Should -BeFalse
        Test-DunePlatformLiveCacheSupported -RuntimePlatform windows | Should -BeTrue
        $env:DST_HOSTING_BACKEND='docker'
        Test-DunePlatformLiveCacheSupported -RuntimePlatform linux | Should -BeTrue
        Test-DunePlatformLiveCacheSupported -RuntimePlatform macos | Should -BeFalse
    }
    It 'uses the packaged native helper and fails closed if it is absent' {
        $env:DST_HOSTING_BACKEND='docker'
        Mock Test-Path { $LiteralPath -eq '/opt/dst/app/tools/platform/DunePlatformStore' }
        Get-DunePlatformHelperPath | Should -Be '/opt/dst/app/tools/platform/DunePlatformStore'
        Mock Test-Path { $false }
        Get-DunePlatformHelperPath | Should -BeNullOrEmpty
    }
    It 'preserves ISO timestamps at the helper JSON boundary' {
        $value=ConvertFrom-DunePlatformJson -Json '{"observedAt":"2026-11-07T22:56:17.8556500+00:00"}'
        ($value.observedAt -is [string]) | Should -BeTrue
        $value.observedAt | Should -BeExactly '2026-11-07T22:56:17.8556500+00:00'
    }
    It 'qualifies only the four bounded cache reads' {
        foreach($path in @('/api/v1/maps/catalog','/api/v1/maps/deep-desert','/api/v1/maps/deep-desert/layers/active-spice','/api/v1/maps/deep-desert/layers/public-poi')) {
            Test-DuneDockerRouteQualified GET $path | Should -BeTrue
            Test-DuneDockerRouteQualified POST $path | Should -BeFalse
        }
        Test-DuneDockerRouteQualified GET '/api/v1/maps/deep-desert/layers/private-poi' | Should -BeFalse
    }
    It 'shares the first cold-start snapshot object before deferred hydration begins' {
        $server=Join-Path $TestDrive 'server'
        [void](New-Item -ItemType Directory -Path $server)
        Copy-Item (Join-Path (Get-DstRepoRoot) 'app/server/HttpServer.ps1') $server
        $script:DunePlatformSnapshotState=$null
        Mock Get-DuneApiCursorSecret { $null }
        try {
            Initialize-DuneApiPool -ServerDir $server
            $state=Get-DunePlatformSnapshotState
            [object]::ReferenceEquals($state,$script:DuneApiCtx.PlatformSnapshotState) | Should -BeTrue
            [void](Set-DunePlatformSnapshot -Snapshot @{generation='hydrated-later'})
            $script:DuneApiCtx.PlatformSnapshotState.snapshot.generation | Should -Be 'hydrated-later'
        } finally {
            if($script:DuneApiPool){$script:DuneApiPool.Dispose();$script:DuneApiPool=$null}
        }
    }
}
