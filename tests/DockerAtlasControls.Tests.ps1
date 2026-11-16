BeforeAll {
    . "$PSScriptRoot\_TestHelpers.ps1"
    Import-DstLib 'Atlas.ps1'
    function global:Test-DuneLocalOnlyRequest { param($Request) return [bool]$Request.loopback }
}

Describe 'Docker Live Map host controls use signed-in roles' {
    BeforeEach { $script:previousHosting=$env:DST_HOSTING_BACKEND; $env:DST_HOSTING_BACKEND='docker' }
AfterEach { $env:DST_HOSTING_BACKEND=$script:previousHosting }

    It 'lets Owner and Admin change timing and collection over LAN or forwarded connections' {
        foreach($role in @('owner','admin')) {
            foreach($loopback in @($true,$false)) {
                Test-DuneAtlasCollectionControl -Request @{loopback=$loopback;Headers=@{'X-Forwarded-For'='192.0.2.10'}} -Principal @{type='portal-account';role=$role} | Should -BeTrue
            }
        }
    }
    It 'does not grant Player, unauthenticated or launch access through loopback or forged capability headers' {
        foreach($principal in @(@{type='linked-player';role='player'},@{type='linked-player';role='owner'},@{type='portal-account';role='player'},@{type='anonymous';role='owner'},@{type='launch-token';role='admin'},@{type='legacy-token';role='owner'},@{},$null)) {
            Test-DuneAtlasCollectionControl -Request @{loopback=$true;Headers=@{'X-DST-Atlas-Timing'='local'}} -Principal $principal | Should -BeFalse
        }
    }
    It 'retains independent per-account map selections for Docker administrators' {
        $request=@{loopback=$false;Headers=@{};Cookies=@{}}
        $owner=@{type='portal-account';role='owner';account=@{id='owner-account'}}
        $admin=@{type='portal-account';role='admin';account=@{id='admin-account'}}
        Test-DuneAtlasCollectionControl -Request $request -Principal $owner | Should -BeTrue
        Test-DuneAtlasCollectionControl -Request $request -Principal $admin | Should -BeTrue
        $first=Get-DuneAtlasPreferenceIdentity -Request $request -Principal $owner -Local $false
        $second=Get-DuneAtlasPreferenceIdentity -Request $request -Principal $admin -Local $false
        $first | Should -Match '^user-[a-f0-9]{64}$'
        $first | Should -Not -Be $second
    }
    It 'retains Windows host-only controls even for a remote Owner' {
        $env:DST_HOSTING_BACKEND='hyper-v'
        Test-DuneAtlasCollectionControl -Request @{loopback=$false} -Principal @{type='portal-account';role='owner'} | Should -BeFalse
        Test-DuneAtlasCollectionControl -Request @{loopback=$true} -Principal @{type='local-host'} | Should -BeTrue
    }
}
