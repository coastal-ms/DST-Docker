BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'RemoteIdentity.ps1'
    Import-DstLib 'PortalAuth.ps1'
    Import-DstLib 'DockerOwnerSetup.ps1'
}
Describe 'Host-side Docker Owner recovery' {
    BeforeEach {
        $script:priorBackend=$env:DST_HOSTING_BACKEND;$env:DST_HOSTING_BACKEND='docker'
        $script:priorAppData=$env:APPDATA;$env:APPDATA=Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        $script:first=(New-DunePortalAccount -Username FirstOwner -Role owner -Password 'first-original-password12').account
        $script:second=(New-DunePortalAccount -Username 'Second Owner' -Role owner -Password 'second-original-password12').account
        $script:admin=(New-DunePortalAccount -Username FixtureAdmin -Role admin -Password 'admin-original-password12').account
        $store=Get-DunePortalAccountStore;$store.accountLoginEnabled=$true
        $selected=Get-DunePortalAccountById $store $script:second.id
        $selected.enabled=$false;$selected.failedCount=10;$selected.lockoutUntil='2099-01-01T00:00:00Z'
        $store.clientFailures=@(@{key='fixture-client';count=20;lockoutUntil='2099-01-01T00:00:00Z'})
        Save-DunePortalAccountStore $store
        $script:firstSession=New-DunePortalSession -AccountId $script:first.id
        $script:secondSession=New-DunePortalSession -AccountId $script:second.id
    }
    AfterEach {$env:DST_HOSTING_BACKEND=$script:priorBackend;$env:APPDATA=$script:priorAppData}
    It 'lists only Owner names and status without password metadata' {
        $result=Get-DuneDockerOwnersForHost
        @($result.owners).Count|Should -Be 2
        ($result|ConvertTo-Json -Depth 5)|Should -Not -Match 'salt|hash|original-password|FixtureAdmin'
    }
    It 'requires exact confirmation and an unambiguous existing Owner before any change' {
        $before=[IO.File]::ReadAllText((Get-DunePortalAccountsPath))
        foreach($name in @('MissingOwner','FixtureAdmin')){
            {Reset-DuneDockerOwnerForHost -Username $name -Confirmation 'RESET OWNER'}|Should -Throw '*existing Owner*'
        }
        {Reset-DuneDockerOwnerForHost -Username 'Second Owner' -Confirmation 'yes'}|Should -Throw '*RESET OWNER*'
        [IO.File]::ReadAllText((Get-DunePortalAccountsPath))|Should -BeExactly $before
        $store=Get-DunePortalAccountStore;$store.accounts+=@{id=('a'*32);normalizedUsername='second owner';role='owner'};Save-DunePortalAccountStore $store
        {Reset-DuneDockerOwnerForHost -Username 'Second Owner' -Confirmation 'RESET OWNER'}|Should -Throw '*Exactly one*'
    }
    It 'recovers only the chosen Owner, revokes their sessions and forces a password replacement' {
        $result=Reset-DuneDockerOwnerForHost -Username 'Second Owner' -Confirmation 'RESET OWNER'
        $store=Get-DunePortalAccountStore;$target=Get-DunePortalAccountById $store $script:second.id
        $target.enabled|Should -BeTrue;$target.mustChangePassword|Should -BeTrue
        $target.failedCount|Should -Be 0;$target.lockoutUntil|Should -Be ''
        $store.accountLoginEnabled|Should -BeTrue;@($store.clientFailures).Count|Should -Be 0
        Test-DunePortalPassword $result.oneTimePassword $target.password|Should -BeTrue
        Test-DunePortalPassword 'first-original-password12' (Get-DunePortalAccountById $store $script:first.id).password|Should -BeTrue
        Test-DunePortalPassword 'admin-original-password12' (Get-DunePortalAccountById $store $script:admin.id).password|Should -BeTrue
        @((Get-DunePortalSessionStore).sessions).Count|Should -Be 1
        (Get-DunePortalSessionStore).sessions[0].accountId|Should -Be $script:first.id
        [IO.File]::ReadAllText((Get-DunePortalAccountsPath))|Should -Not -Match ([regex]::Escape($result.oneTimePassword))
    }
    It 'does not fall back to a saved store when the primary account file is unreadable' {
        $path=Get-DunePortalAccountsPath;[IO.File]::WriteAllText($path,'corrupt-primary')
        {Reset-DuneDockerOwnerForHost -Username 'Second Owner' -Confirmation 'RESET OWNER'}|Should -Throw '*needs review*'
        [IO.File]::ReadAllText($path)|Should -BeExactly 'corrupt-primary'
    }
    It 'does not commit a new password when session revocation fails' {
        $before=[IO.File]::ReadAllText((Get-DunePortalAccountsPath))
        Mock Revoke-DunePortalSessions {throw 'Session storage is unavailable.'}
        {Reset-DuneDockerOwnerForHost -Username 'Second Owner' -Confirmation 'RESET OWNER'}|Should -Throw '*Session storage*'
        [IO.File]::ReadAllText((Get-DunePortalAccountsPath))|Should -BeExactly $before
    }
}
