BeforeAll {
    . "$PSScriptRoot\_TestHelpers.ps1"
    . (Join-Path (Get-DstRepoRoot) 'app/server/HttpServer.ps1')
    Import-DstLib 'DockerRoutes.ps1'
    Import-DstLib 'DockerFileBrowser.ps1'
    Import-DstLib 'Links.ps1'
    function global:Invoke-DuneDockerManager {param($Request)}
}
Describe 'Director UI through the Docker console' {
    It 'keeps every proxy method under the exact Owner-only path' {
        foreach($method in @('GET','HEAD','POST','PUT','PATCH','DELETE')){
            Test-DuneDockerRouteQualified $method '/api/docker/director/Script/main.js'|Should -BeTrue
            Test-DunePortalOwnerOnlyPath '/api/docker/director/Script/main.js' $method|Should -BeTrue
        }
        Test-DuneDockerRouteQualified GET '/api/docker/director-other/'|Should -BeFalse
        Test-DuneDockerRouteQualified OPTIONS '/api/docker/director/'|Should -BeFalse
    }
    It 'keeps native assets and browser API requests under the console prefix' {
        $html='<html><head><link href="Stylesheet/test.css"><script src="/Script/main.js"></script></head><body><a href="https://example.org/">Help</a></body></html>'
        $result=ConvertTo-DuneDockerDirectorHtml $html -Port 29777
        $result|Should -Match '<base href="/api/docker/director/">'
        $result|Should -Match 'src="/api/docker/director/Script/main.js"'
        $result|Should -Match 'XMLHttpRequest.prototype.open'
        $result|Should -Match 'window.fetch='
        $result|Should -Match 'href="https://example.org/"'
    }
    It 'returns the console-relative Director link instead of the viewer loopback address' {
        $saved=$env:DST_HOSTING_BACKEND
        try {
            $env:DST_HOSTING_BACKEND='docker'
            Mock Invoke-DuneDockerManager { @{ok=$true;data=@{services=@(@{component='director';state='running'});plan=@{ports=@{director=29777}}}} }
            $links=Get-DuneLinks
            $links.director.available|Should -BeTrue
            $links.director.url|Should -Be '/api/docker/director/'
        } finally {$env:DST_HOSTING_BACKEND=$saved}
    }
}
