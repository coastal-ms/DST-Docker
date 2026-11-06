BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'GameConfig.ps1'
    Import-DstLib 'BrowserClientSettings.ps1'
}
Describe 'Browser-selected client INI transformation' {
    BeforeEach {
        $script:request=@{mode='apply';selected=$true;approved=$true;engineEnabled=$true;directory='Windows';reviewedRaw=$false;
            files=@{game=@{exists=$true;raw="; Manual comment`n[Manual]`nKeep=unchanged`n"};engine=@{exists=$true;raw="[ConsoleVariables]`nVehicle.MaxVehiclesPerPlayer=10`nManual.Other=preserved`n"}};
            updates=@(@{file='engine';section='ConsoleVariables';key='Vehicle.MaxVehiclesPerPlayer';value='20'})}
    }
    It 'uses the existing INI merger while preserving unrelated values and the original bytes for browser backup' {
        $result=Convert-DuneBrowserClientSettings -Request $script:request
        $result.client.engine.effective['ConsoleVariables||Vehicle.MaxVehiclesPerPlayer']|Should -BeExactly '20'
        $result.client.engine.effective['ConsoleVariables||Manual.Other']|Should -BeExactly 'preserved'
        $result.client.game.raw|Should -BeExactly $script:request.files.game.raw
        $result.changes.engine.before|Should -BeExactly $script:request.files.engine.raw
        $result.changes.Keys.Count|Should -Be 1
    }
    It 'does not accept arbitrary compatibility keys or engine writes without opt-in' {
        $script:request.updates[0].key='Manual.Other'
        {Convert-DuneBrowserClientSettings -Request $script:request}|Should -Throw '*not approved*'
        $script:request.updates[0].key='Vehicle.MaxVehiclesPerPlayer';$script:request.engineEnabled=$false
        {Convert-DuneBrowserClientSettings -Request $script:request}|Should -Throw '*not approved*'
    }
    It 'requires explicit selection and review before creating a changed file' {
        $script:request.selected=$false
        {Convert-DuneBrowserClientSettings -Request $script:request}|Should -Throw '*Choose your client files*'
        $script:request.selected=$true;$script:request.approved=$false
        {Convert-DuneBrowserClientSettings -Request $script:request}|Should -Throw '*review*'
    }
    It 'projects an unselected client without attempting host file access' {
        $script:request.mode='inspect';$script:request.selected=$false
        $result=Convert-DuneBrowserClientSettings -Request $script:request
        $result.client.dirExists|Should -BeFalse
        $result.applied|Should -Be 0
        $result.changes.Count|Should -Be 0
    }
    It 'rejects multiline values and oversized file payloads' {
        $script:request.updates[0].value="20`nInjected=1"
        {Convert-DuneBrowserClientSettings -Request $script:request}|Should -Throw '*scalar*'
        $script:request.updates[0].value='20';$script:request.files.game.raw='x'*(1MB+1)
        {Convert-DuneBrowserClientSettings -Request $script:request}|Should -Throw '*1 MiB*'
    }
    It 'removes only known managed engine values when management is disabled' {
        $script:request.mode='disable-engine';$script:request.engineEnabled=$false
        $result=Convert-DuneBrowserClientSettings -Request $script:request
        $result.removed|Should -Be 1
        $result.client.engine.effective.ContainsKey('ConsoleVariables||Vehicle.MaxVehiclesPerPlayer')|Should -BeFalse
        $result.client.engine.effective['ConsoleVariables||Manual.Other']|Should -BeExactly 'preserved'
    }
}
