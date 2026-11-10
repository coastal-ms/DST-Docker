BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'PortalAuth.ps1'
    Import-DstLib 'RequestPrincipal.ps1'
    . (Join-Path (Get-DstRepoRoot) 'app/server/HttpServer.ps1')
}
Describe 'Native browser account session boundaries' {
    BeforeEach {$script:priorBackend=$env:DST_HOSTING_BACKEND;$env:DST_HOSTING_BACKEND='docker'}
    AfterEach {$env:DST_HOSTING_BACKEND=$script:priorBackend}
    It 'does not accept the installer launch token as a post-setup session even on loopback' {
        Mock Test-DuneLaunchToken {$true}
        Mock Test-DuneLocalOnlyRequest {$true}
        Test-DuneAccountModeLaunchAccess -Request @{}|Should -BeFalse
    }
    It 'preserves the acting Owner cookie when another account is revoked or reset' {
        $response=[pscustomobject]@{Headers=@{}}
        Clear-DunePortalManagedAccountCookie -Response $response -RouteParams @{requestPrincipal=@{account=@{id='acting-owner'}}} -AccountId 'another-admin'
        $response.Headers.ContainsKey('Set-Cookie')|Should -BeFalse
        Clear-DunePortalManagedAccountCookie -Response $response -RouteParams @{requestPrincipal=@{account=@{id='acting-owner'}}} -AccountId 'acting-owner'
        $response.Headers['Set-Cookie']|Should -Match 'Max-Age=0'
    }
    It 'retains the Windows host cookie clearing behavior' {
        $env:DST_HOSTING_BACKEND=''
        $response=[pscustomobject]@{Headers=@{}}
        Clear-DunePortalManagedAccountCookie -Response $response -AccountId 'another-admin'
        $response.Headers['Set-Cookie']|Should -Match 'Max-Age=0'
    }
}
