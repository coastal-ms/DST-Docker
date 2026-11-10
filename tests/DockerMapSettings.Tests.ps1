BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'GameConfig.ps1'
    Import-DstLib 'RetailServerSettings.ps1'
    Import-DstLib 'DockerSettings.ps1'
    function global:Invoke-DuneDockerManager {param($Request)}
}

Describe 'Per-map settings use the selected scope and established writers' {
    It 'matches memory observations to this world containers rather than a reused partition number' {
        $samples=@{available=$true;observedAt=100;containers=@(
            @{name='dst-other-game-2';component='game-2';memory=@{usedBytes=123}},
            @{name='dst-own-game-2';component='game-2';memory=@{usedBytes=456}},
            @{name='dst-own-game-2-previous-12345678';component='game-2';memory=@{usedBytes=789}}
        )}
        $result=Select-DuneDockerMapSamples -Samples $samples -Services @(@{name='dst-own-game-2';component='game-2'})
        $result.containers.Count|Should -Be 1
        $result.containers[0].memory.usedBytes|Should -Be 456
        $result.observedAt|Should -Be 100
        $samples.containers.Count|Should -Be 3
    }
    BeforeEach {
        $script:raw="; preserve`n[/Script/DuneSandbox.UserServerCustomSettings]`nDifficultyLevel=Custom`nPVPMode=Limited`nGatheringAmount=1.0`nFutureKey=42`n"
        $script:revision='a'*64
        $script:requests=[Collections.Generic.List[object]]::new()
        Mock Invoke-DuneDockerManager {
            param($Request)
            $script:requests.Add($Request)
            if($Request.action -eq 'status'){return @{ok=$true;data=@{services=@(@{component='game-1'});plan=@{games=@(@{partition=1;map='Survival_1'},@{partition=8;map='DeepDesert_1'})}}}}
            if($Request.action -eq 'map-settings.write'){$script:raw=$Request.raw}
            return @{ok=$true;data=@{raw=$script:raw;revision=$script:revision;overridden=$true;pendingRestart=$true;adapterReady=$true}}
        }
    }
    It 'writes only the requested partition and preserves unknown values' {
        $result=Save-DuneDockerMapSettings @{target='8';file='server';revision=$script:revision;updates=@{GatheringAmount='2.5';PVPMode='NoPVP'};inherit=$false}
        $writes=@($script:requests|Where-Object action -eq 'map-settings.write')
        $writes.Count | Should -Be 1
        $writes[0].target | Should -BeExactly '8'
        $writes[0].raw | Should -Match 'GatheringAmount=2.5'
        $writes[0].raw | Should -Match 'PVPMode=NoPVP'
        $writes[0].raw | Should -Match 'FutureKey=42'
        $result.pendingRestart | Should -BeTrue
    }
    It 'offers Global defaults and only Hagga and Deep Desert gameplay scopes' {
        Mock Get-DuneDockerSettingsContext { @{ok=$true;native=@{plan=@{games=@(
            @{partition=1;map='Survival_1'},@{partition=2;map='Overmap'},@{partition=3;map='SH_Arrakeen'},
            @{partition=8;map='DeepDesert_1'},@{partition=9;map='CB_Story_Test'}
        )}}} }
        $targets=(Get-DuneDockerMapSettings).targets
        @($targets.id) | Should -Be @('global','1','8')
        {Get-DuneDockerMapSettings -Target '3'} | Should -Throw '*Global defaults*'
        {Save-DuneDockerMapSettings @{target='global';file='server';revision=$script:revision;inherit=$true}} | Should -Throw '*cannot inherit*'
    }
    It 'rejects stale or unsupported updates before writing' {
        {Save-DuneDockerMapSettings @{target='8';file='server';revision=('b'*64);updates=@{GatheringAmount='2'};inherit=$false}} | Should -Throw '*changed*'
        {Save-DuneDockerMapSettings @{target='8';file='server';revision=$script:revision;updates=@{Unknown='2'};inherit=$false}} | Should -Throw '*not editable*'
        @($script:requests|Where-Object action -eq 'map-settings.write').Count | Should -Be 0
    }
    It 'derives game fields from the supported schema without exposing startup commands or struct editors' {
        $fields=@(Get-DuneDockerMapSettingFields -File game -Raw '')
        $fields.Count | Should -BeGreaterThan 0
        @($fields|Where-Object {$_.structKey -or $_.consoleVar}).Count | Should -Be 0
        @($fields|Where-Object {$_.key -match 'password|token|secret'}).Count | Should -Be 0
    }
}
