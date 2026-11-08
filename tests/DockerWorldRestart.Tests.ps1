BeforeAll {
    . "$PSScriptRoot\_TestHelpers.ps1"
    function Invoke-DuneDockerManager {param($Request) throw 'Mock required'}
    Import-DstLib 'WorldRestart.ps1'
}
Describe 'Native World Restart maintenance status' {
    BeforeEach {$script:previousBackend=$env:DST_HOSTING_BACKEND;$env:DST_HOSTING_BACKEND='docker'}
    AfterEach {$env:DST_HOSTING_BACKEND=$script:previousBackend}
    It 'uses the native journal and blocks commands throughout reset and research recovery' {
        Mock Invoke-DuneDockerManager {@{ok=$true;data=@{phase='preparing-fresh-schema';running=$true;recoveryRequired=$false}}}
        (Get-DuneWorldRestartStatus).phase|Should -Be 'preparing-fresh-schema'
        Test-DuneWorldRestartMaintenanceActive|Should -BeTrue
        Mock Invoke-DuneDockerManager {@{ok=$true;data=@{phase='done';running=$false;recoveryRequired=$true}}}
        Test-DuneWorldRestartMaintenanceActive|Should -BeTrue
        Should -Invoke Invoke-DuneDockerManager -ParameterFilter {$Request.action -eq 'world-restart.status'}
    }
    It 'never treats unavailable native maintenance evidence as an idle world' {
        Mock Invoke-DuneDockerManager {@{ok=$false;error='unavailable'}}
        {Get-DuneWorldRestartStatus}|Should -Throw '*unavailable*'
    }
}
