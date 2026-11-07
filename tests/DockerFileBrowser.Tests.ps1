BeforeAll {
    . "$PSScriptRoot\_TestHelpers.ps1"
    . (Join-Path (Get-DstRepoRoot) 'app/server/HttpServer.ps1')
    . (Join-Path (Get-DstRepoRoot) 'app/server/lib/DockerRoutes.ps1')
}
Describe 'Docker File Browser routing' {
    It 'passes explicit streaming metadata into the pooled HTTP worker only' {
        (Get-Command Invoke-DuneApiHandlerAsync).Parameters.ContainsKey('StreamBody') | Should -BeTrue
        (Get-Command Invoke-DuneWsHandlerAsync).Parameters.ContainsKey('StreamBody') | Should -BeFalse
    }
    It 'matches empty and nested suffixes without widening the prefix' {
        Register-DuneRoute -Method HEAD -Path '/api/docker/file-browser/{path*}' -StreamBody -Handler {}
        $route=$script:DuneRoutes[$script:DuneRoutes.Count-1]
        $route.Regex.IsMatch('/api/docker/file-browser/') | Should -BeTrue
        $route.Regex.IsMatch('/api/docker/file-browser/api/raw/nested/a%20b.bin') | Should -BeTrue
        $route.Regex.IsMatch('/api/docker/file-browser-other/') | Should -BeFalse
        $route.StreamBody | Should -BeTrue
        $route.Inline | Should -BeFalse
    }
    It 'preserves ordinary one-segment route matching and buffered defaults' {
        Register-DuneRoute -Method GET -Path '/api/test/{id}' -Handler {}
        $route=$script:DuneRoutes[$script:DuneRoutes.Count-1]
        $route.Regex.Match('/api/test/abc').Groups['id'].Value | Should -Be 'abc'
        $route.Regex.IsMatch('/api/test/abc/def') | Should -BeFalse
        $route.StreamBody | Should -BeFalse
    }
    It 'refuses a streaming handler on the listener thread' {
        { Register-DuneRoute -Method POST -Path '/api/test' -Inline -StreamBody -Handler {} } | Should -Throw '*pooled worker*'
    }
    It 'qualifies only the helper prefix and supported transfer methods' {
        foreach($method in @('GET','HEAD','POST','PUT','PATCH','DELETE')){
            Test-DuneDockerRouteQualified $method '/api/docker/file-browser/api/resources/test' | Should -BeTrue
            Test-DunePortalOwnerOnlyPath '/api/docker/file-browser/api/resources/test' $method | Should -BeTrue
        }
        Test-DuneDockerRouteQualified OPTIONS '/api/docker/file-browser/' | Should -BeFalse
        Test-DuneDockerRouteQualified GET '/api/docker/file-browser-other/' | Should -BeFalse
    }
}
