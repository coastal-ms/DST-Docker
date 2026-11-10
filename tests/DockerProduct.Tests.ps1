BeforeAll {
    . "$PSScriptRoot/../app/server/lib/DockerProduct.ps1"
}
Describe 'Independent Docker product identity' {
    It 'loads its own release version and repository' {
        $product=Get-DuneDockerProduct
        $product.name|Should -BeExactly 'DST Docker'
        $product.version|Should -BeExactly '1.0.0'
        $product.repository|Should -BeExactly 'coastal-ms/DST-Docker'
        $product.tag|Should -BeExactly 'v1.0.0'
    }
    It 'rejects a mixed Windows product identity' {
        $path=Join-Path $TestDrive 'wrong.json'
        @{name='Dune Server Tool';version='1.0.0';repository='coastal-ms/DST-DuneServerTool';tag='v1.0.0'}|ConvertTo-Json|Set-Content $path
        {Get-DuneDockerProduct -Path $path}|Should -Throw '*identity is invalid*'
    }
}
