BeforeAll {
    . "$PSScriptRoot\_TestHelpers.ps1"
    Import-DstLib 'RegisTanks.ps1'
    Import-DstLib 'DockerRoutes.ps1'
    Import-DstLib 'Commands.ps1'
    function global:Invoke-DuneDockerManager { param($Request) }
    function global:Resolve-DuneRetailServerSettingsTarget { param($Ip) }
    function global:Invoke-V6Ssh { param($Ip,$Cmd,$TimeoutSec) }
    function global:Invoke-DuneSqlQuery { param($Ip,$Sql,$ReadOnly,$MaxRows,$TimeoutSec) }
    function global:ConvertTo-DuneRowMaps { param($Result); return $Result.rows }
}
Describe 'Docker Tank readiness and recovery boundaries' {
    BeforeEach {
        $script:oldBackend=$env:DST_HOSTING_BACKEND; $env:DST_HOSTING_BACKEND='docker'
        Mock Invoke-DuneDockerManager { @{ok=$true;data=@{enabled=$true;build='2173753'}} }
        Mock Resolve-DuneRetailServerSettingsTarget { throw 'VM path used' }
        Mock Invoke-V6Ssh { throw 'SSH used' }
        Mock Invoke-DuneSqlQuery { @{ok=$true;rows=@(@{map='HaggaBasin'})} }
        Mock ConvertTo-DuneRowMaps { return ,@(@{map='HaggaBasin'}) }
    }
    AfterEach { $env:DST_HOSTING_BACKEND=$script:oldBackend }
    It 'verifies the online actor map before using native compatibility checks' {
        (Get-DuneRegisTankSupport -Ip docker -ActorId 544).enabled | Should -BeTrue
        Should -Invoke Invoke-DuneSqlQuery -Times 1 -ParameterFilter {$ReadOnly -and $Sql -match '544::bigint'}
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'regis.support'}
        Should -Invoke Resolve-DuneRetailServerSettingsTarget -Times 0
        Should -Invoke Invoke-V6Ssh -Times 0
    }
    It 'refuses offline and non-Hagga actors without invoking the native grant gate' {
        Mock Invoke-DuneSqlQuery { @{ok=$true;rows=@(@{map='DeepDesert'})} }
        Mock ConvertTo-DuneRowMaps { return ,@(@{map='DeepDesert'}) }
        (Get-DuneRegisTankSupport -Ip docker -ActorId 544).enabled | Should -BeFalse
        Mock Invoke-DuneSqlQuery { @{ok=$true;rows=@()} }
        Mock ConvertTo-DuneRowMaps { return ,@() }
        (Get-DuneRegisTankSupport -Ip docker -ActorId 544).enabled | Should -BeFalse
        Should -Invoke Invoke-DuneDockerManager -Times 0
    }
    It 'blocks lifecycle and updates during recovery while retaining stop and log exports' {
        $state=@{hostingBackend='docker';operation=@{};regisPending=$true;prepared=$true;desiredState='running'}
        foreach($name in @('start','restart','apply-inis','update')) {
            (Get-DuneCommandAvailability -Command @{Name=$name} -State $state).available | Should -BeFalse
        }
        foreach($name in @('stop','logs-export','operator-logs-export')) {
            (Get-DuneCommandAvailability -Command @{Name=$name} -State $state).available | Should -BeTrue
        }
    }
    It 'qualifies exact Tank routes without widening methods or suffixes' {
        Test-DuneDockerRouteQualified GET '/api/gameconfig/regis-tanks' | Should -BeTrue
        Test-DuneDockerRouteQualified PUT '/api/gameconfig/regis-tanks' | Should -BeTrue
        Test-DuneDockerRouteQualified POST '/api/gameconfig/regis-tanks/recover' | Should -BeTrue
        Test-DuneDockerRouteQualified GET '/api/gameplay/vehicles/regis-tanks' | Should -BeTrue
        Test-DuneDockerRouteQualified POST '/api/gameplay/vehicles/regis-tanks' | Should -BeTrue
        Test-DuneDockerRouteQualified GET '/api/gameconfig/regis-tanks/recover' | Should -BeFalse
        Test-DuneDockerRouteQualified POST '/api/gameconfig/regis-tanks' | Should -BeFalse
        Test-DuneDockerRouteQualified PUT '/api/gameconfig/regis-tanks/extra' | Should -BeFalse
    }
}
