BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'PortalAuth.ps1'
    . (Join-Path (Get-DstRepoRoot) 'app/server/HttpServer.ps1')
    $script:HttpsOldBackend=$env:DST_HOSTING_BACKEND
    $script:HttpsOldConfig=$env:DST_TLS_PROXY_CONFIG
    $env:DST_HOSTING_BACKEND='docker'
    $env:DST_TLS_PROXY_CONFIG=Join-Path $TestDrive 'proxy.json'
    $script:HttpsSecret='a'*64
    function New-TlsRequest {
        return [pscustomobject]@{
            Url=[uri]'http://127.0.0.1:8288/api/portal-auth/login'
            RemoteEndPoint=[pscustomobject]@{Address=[Net.IPAddress]::Loopback}
            Headers=@{Host='192.0.2.10:8443';Origin='https://192.0.2.10:8443';'X-Dst-Tls-Proxy'=$script:HttpsSecret;'X-Forwarded-Proto'='https';'X-Forwarded-For'='192.0.2.50'}
        }
    }
}
AfterAll {
    $env:DST_HOSTING_BACKEND=$script:HttpsOldBackend
    $env:DST_TLS_PROXY_CONFIG=$script:HttpsOldConfig
}
Describe 'Paired Docker HTTPS proxy' {
    BeforeEach {
        $env:DST_HOSTING_BACKEND='docker'
        @{origin='https://192.0.2.10:8443';secret=$script:HttpsSecret}|ConvertTo-Json|Set-Content $env:DST_TLS_PROXY_CONFIG
    }
    It 'accepts the paired external origin and emits Secure account cookies' {
        $request=New-TlsRequest
        Test-DunePortalRequestOrigin $request|Should -BeTrue
        $response=[pscustomobject]@{Headers=@{}}
        Set-DunePortalSessionCookie $response 'synthetic-token' -Request $request
        $response.Headers['Set-Cookie']|Should -Match '; Secure; HttpOnly; SameSite=Strict'
        Clear-DunePortalSessionCookie $response -Request $request
        $response.Headers['Set-Cookie']|Should -Match '; Secure; HttpOnly; SameSite=Strict'
        Test-DuneLocalOnlyRequest $request|Should -BeFalse
    }
    It 'rejects HTTPS claims without a valid pairing secret' {
        foreach($secret in @('',('b'*64))){
            $request=New-TlsRequest;$request.Headers['X-Dst-Tls-Proxy']=$secret
            Test-DunePortalRequestOrigin $request|Should -BeFalse
        }
    }
    It 'rejects non-loopback peers even if they supply the pairing proof' {
        $request=New-TlsRequest;$request.RemoteEndPoint.Address=[Net.IPAddress]::Parse('192.0.2.51')
        Test-DunePortalRequestOrigin $request|Should -BeFalse
    }
    It 'rejects a changed host, origin, scheme, or port' {
        foreach($change in @(@{Host='evil.example:8443'},@{Origin='https://evil.example:8443'},@{Origin='https://192.0.2.10:8444'},@{'X-Forwarded-Proto'='http'})){
            $request=New-TlsRequest;foreach($key in $change.Keys){$request.Headers[$key]=$change[$key]}
            Test-DunePortalRequestOrigin $request|Should -BeFalse
        }
    }
    It 'fails closed over a missing or malformed pairing configuration' {
        foreach($raw in @('{','{}','{"origin":"http://192.0.2.10:8443","secret":"bad"}')){
            Set-Content $env:DST_TLS_PROXY_CONFIG $raw
            Test-DunePortalRequestOrigin (New-TlsRequest)|Should -BeFalse
        }
        Remove-Item $env:DST_TLS_PROXY_CONFIG
        Test-DunePortalRequestOrigin (New-TlsRequest)|Should -BeFalse
    }
    It 'keeps existing direct HTTP IP login and standalone origin rules' {
        $request=New-TlsRequest;$request.Headers=@{Host='192.0.2.10:8088';Origin='http://192.0.2.10:8088'}
        Test-DunePortalRequestOrigin $request|Should -BeTrue
        $response=[pscustomobject]@{Headers=@{}}
        Set-DunePortalSessionCookie $response 'synthetic-token' -Request $request
        $response.Headers['Set-Cookie']|Should -Not -Match '; Secure'
        $env:DST_HOSTING_BACKEND=''
        Get-DuneDockerTlsOrigin (New-TlsRequest)|Should -BeNullOrEmpty
    }
}
