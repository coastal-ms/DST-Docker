BeforeAll {
    . "$PSScriptRoot/../app/server/lib/DockerProduct.ps1"
}
Describe 'Independent Docker product identity' {
    It 'loads its own release version and repository' {
        $path=Join-Path $TestDrive 'docker-release.json'
        @{name='DST Docker';version='1.2.3';repository='coastal-ms/DST-Docker';tag='v1.2.3'}|ConvertTo-Json|Set-Content $path
        $product=Get-DuneDockerProduct -Path $path
        $product.name|Should -BeExactly 'DST Docker'
        $product.version|Should -BeExactly '1.2.3'
        $product.repository|Should -BeExactly 'coastal-ms/DST-Docker'
        $product.tag|Should -BeExactly 'v1.2.3'
    }
    It 'keeps the committed Docker release and frontend versions consistent' {
        $product=Get-DuneDockerProduct
        $frontend=Get-Content (Join-Path $PSScriptRoot '../webui/package.json') -Raw|ConvertFrom-Json
        $product.version|Should -BeExactly $frontend.version
        $product.tag|Should -BeExactly ('v'+$frontend.version)
        $product.repository|Should -BeExactly 'coastal-ms/DST-Docker'
    }
    It 'rejects a mixed Windows product identity' {
        $path=Join-Path $TestDrive 'wrong.json'
        @{name='Dune Server Tool';version='1.0.0';repository='coastal-ms/DST-DuneServerTool';tag='v1.0.0'}|ConvertTo-Json|Set-Content $path
        {Get-DuneDockerProduct -Path $path}|Should -Throw '*identity is invalid*'
    }
}
