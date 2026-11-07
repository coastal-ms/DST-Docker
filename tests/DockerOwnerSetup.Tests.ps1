BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'RemoteIdentity.ps1'
    Import-DstLib 'PortalAuth.ps1'
    Import-DstLib 'DockerOwnerSetup.ps1'
    . (Join-Path (Get-DstRepoRoot) 'app/server/HttpServer.ps1')
}
Describe 'First Docker owner setup' {
    BeforeEach {
        $script:previousBackend=$env:DST_HOSTING_BACKEND;$env:DST_HOSTING_BACKEND='docker'
        $script:previousAppData=$env:APPDATA;$env:APPDATA=Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        $script:DuneToken='synthetic-bootstrap-key'
        $script:request=[pscustomobject]@{Url=[uri]'http://192.0.2.23:8088/';Headers=@{'X-Dune-Token'=$script:DuneToken;Origin='http://192.0.2.23:8088'};QueryString=@{};
            RemoteEndPoint=[pscustomobject]@{Address=[Net.IPAddress]::Parse('192.0.2.24')};Cookies=@{}}
    }
    AfterEach {$env:DST_HOSTING_BACKEND=$script:previousBackend;$env:APPDATA=$script:previousAppData}
    It 'atomically creates one chosen owner and enables normal account login' {
        (Get-DuneDockerOwnerSetupState).required|Should -BeTrue
        $result=New-DuneDockerOwner -Username FixtureOwner -Password 'synthetic-owner-password' -Request $script:request
        $result.account.role|Should -Be owner
        $result.account.mustChangePassword|Should -BeFalse
        $result.token|Should -Not -BeNullOrEmpty
        (Get-DuneDockerOwnerSetupState).required|Should -BeFalse
        Test-DunePortalAccountModeEnabled|Should -BeTrue
        $raw=Get-Content (Get-DunePortalAccountsPath) -Raw
        $raw|Should -Not -Match 'synthetic-owner-password'
        $account=(Get-DunePortalAccountStore).accounts[0]
        Test-DunePortalPassword 'synthetic-owner-password' $account.password|Should -BeTrue
        {New-DuneDockerOwner -Username Replacement -Password 'different-test-password' -Request $script:request}|Should -Throw '*already complete*'
        (Get-DunePortalAccountStore).accounts.Count|Should -Be 1
        (Get-DunePortalAccountStore).accounts[0].username|Should -Be FixtureOwner
    }
    It 'requires both the bootstrap key and an exact same-origin request before creating anything' {
        $script:request.Headers['X-Dune-Token']='wrong-key'
        {New-DuneDockerOwner -Username FixtureOwner -Password 'synthetic-owner-password' -Request $script:request}|Should -Throw '*private installer link*'
        $script:request.Headers['X-Dune-Token']=$script:DuneToken
        foreach($origin in @('http://evil.example','http://192.0.2.23:9090','https://192.0.2.23:8088','null','http://user@192.0.2.23:8088','http://192.0.2.23:8088/path')){
            $script:request.Headers.Origin=$origin
            {New-DuneDockerOwner -Username FixtureOwner -Password 'synthetic-owner-password' -Request $script:request}|Should -Throw '*origin*'
        }
        Test-Path (Get-DunePortalAccountsPath)|Should -BeFalse
    }
    It 'does not reopen setup when an existing account file is unreadable' {
        $path=Get-DunePortalAccountsPath
        [IO.File]::WriteAllText($path,'unreadable fixture')
        [IO.File]::WriteAllText("$path.bak",'{"version":1,"accountLoginEnabled":false,"accounts":[]}')
        {Get-DuneDockerOwnerSetupState}|Should -Throw '*needs review*'
        {New-DuneDockerOwner -Username FixtureOwner -Password 'synthetic-owner-password' -Request $script:request}|Should -Throw '*needs review*'
        [IO.File]::ReadAllText($path)|Should -BeExactly 'unreadable fixture'
    }
    It 'uses the browser Host authority for translated ports without trusting forwarded headers' {
        $script:request.Headers.Host='192.0.2.23:18188'
        $script:request.Headers.Origin='http://192.0.2.23:18188'
        Test-DunePortalRequestOrigin $script:request|Should -BeTrue
        $script:request.Headers.Origin='http://evil.example'
        $script:request.Headers['X-Forwarded-Host']='evil.example'
        Test-DunePortalRequestOrigin $script:request|Should -BeFalse
    }
    It 'uses HTTP-compatible Docker session cookies while retaining HttpOnly and same-site protection' {
        $response=[pscustomobject]@{Headers=@{}}
        Set-DunePortalSessionCookie -Response $response -Token synthetic -Request $script:request -RememberMe $true
        $response.Headers['Set-Cookie']|Should -Match 'HttpOnly; SameSite=Strict'
        $response.Headers['Set-Cookie']|Should -Not -Match '; Secure'
        $response.Headers['Set-Cookie']|Should -Match 'Max-Age=2592000'
        Clear-DunePortalSessionCookie -Response $response -Request $script:request
        $response.Headers['Set-Cookie']|Should -Match 'Max-Age=0'
        $response.Headers['Set-Cookie']|Should -Not -Match '; Secure'
        $script:request.Url=[uri]'https://192.0.2.23:8088/'
        Set-DunePortalSessionCookie -Response $response -Token synthetic -Request $script:request
        $response.Headers['Set-Cookie']|Should -Match '; Secure'
        $env:DST_HOSTING_BACKEND=''
        $script:request.Url=[uri]'http://192.0.2.23:8088/'
        Set-DunePortalSessionCookie -Response $response -Token synthetic -Request $script:request
        $response.Headers['Set-Cookie']|Should -Match '; Secure'
    }
}
