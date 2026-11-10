BeforeAll {
    . "$PSScriptRoot/../app/server/HttpServer.ps1"
}

Describe 'Browser assets across updates' {
    It 'keeps old lazy modules available while serving new page bundles' {
        $dist=Join-Path $TestDrive 'dist';$cache=Join-Path $TestDrive 'cache'
        [void][IO.Directory]::CreateDirectory((Join-Path $dist 'assets'))
        Set-Content (Join-Path $dist 'index.html') 'first build'
        Set-Content (Join-Path $dist 'assets/MapWorkspace-abcdef12.js') 'export default 1'
        Initialize-DuneStaticAssetCache -DistRoot $dist -CacheRoot $cache
        Remove-Item -LiteralPath (Join-Path $dist 'assets/MapWorkspace-abcdef12.js')
        Set-Content (Join-Path $dist 'index.html') 'second build'
        Set-Content (Join-Path $dist 'assets/MapWorkspace-98765432.js') 'export default 2'
        Initialize-DuneStaticAssetCache -DistRoot $dist -CacheRoot $cache
        $script:DuneDistRoot=$dist
        Get-Content (Resolve-DuneStaticPath '/assets/MapWorkspace-abcdef12.js') | Should -Be 'export default 1'
        Get-Content (Resolve-DuneStaticPath '/assets/MapWorkspace-98765432.js') | Should -Be 'export default 2'
        Resolve-DuneRetainedAsset '/assets/../index.html' | Should -BeNullOrEmpty
        Resolve-DuneRetainedAsset '/assets/not-hashed.js' | Should -BeNullOrEmpty
        Resolve-DuneRetainedAsset '/assets/MapWorkspace-abcdef12.js/extra' | Should -BeNullOrEmpty
    }
    It 'bounds retained generations and preserves unrelated cache directories' {
        $dist=Join-Path $TestDrive 'many-dist';$cache=Join-Path $TestDrive 'many-cache'
        [void][IO.Directory]::CreateDirectory((Join-Path $dist 'assets'))
        [void][IO.Directory]::CreateDirectory((Join-Path $cache 'unrelated'))
        1..6 | ForEach-Object {
            Set-Content (Join-Path $dist 'index.html') "build $_"
            Set-Content (Join-Path $dist "assets/Page-abcdef$_.js") "export default $_"
            Initialize-DuneStaticAssetCache -DistRoot $dist -CacheRoot $cache
        }
        @($script:DuneAssetGenerations).Count | Should -Be 5
        @(Get-ChildItem $cache -Directory | Where-Object Name -Match '^[a-f0-9]{64}$').Count | Should -Be 5
        Test-Path (Join-Path $cache 'unrelated') | Should -BeTrue
    }
}
