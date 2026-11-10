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
    It 'preserves both scalar and array parts of a reviewed staking-timer update and clears both on disable' {
        $script:request.reviewedRaw=$true
        $script:request.updates=Build-DuneLandclaimUpdates -Enabled $true -Seconds '2.5' -File game
        $enabled=Convert-DuneBrowserClientSettings -Request $script:request
        $state=Get-DuneLandclaimTimerState -Raw $enabled.client.game.raw
        $state.enabled|Should -BeTrue
        $state.formattedOk|Should -BeTrue
        $state.seconds|Should -Be '2.5'
        $enabled.client.game.effective['Manual||Keep']|Should -Be 'unchanged'
        $script:request.files.game.raw=$enabled.client.game.raw
        $removals=Build-DuneLandclaimUpdates -Enabled $false -Seconds '' -File game
        $script:request.updates=@(foreach($item in $removals){@{file=$item.file;section=$item.section;key=$item.key;value='';arrayLines=@()}})
        $disabled=Convert-DuneBrowserClientSettings -Request $script:request
        (Get-DuneLandclaimTimerState -Raw $disabled.client.game.raw).hasOverrides|Should -BeFalse
        $disabled.client.game.effective['Manual||Keep']|Should -Be 'unchanged'
    }
    It 'generates only the shared timer keys for the dedicated browser operation' {
        $script:request.mode='landclaim';$script:request.reviewedRaw=$false
        $script:request.timerEnabled=$true;$script:request.timerSeconds='2.5'
        $script:request.updates=@(@{file='engine';section='ConsoleVariables';key='Manual.Other';value='injected'})
        $result=Convert-DuneBrowserClientSettings -Request $script:request
        $result.client.landclaimTimer.enabled|Should -BeTrue
        $result.client.landclaimTimer.formattedOk|Should -BeTrue
        $result.client.landclaimTimer.seconds|Should -Be '2.5'
        $result.client.engine.raw|Should -BeExactly $script:request.files.engine.raw
        $result.client.game.effective['Manual||Keep']|Should -Be 'unchanged'
        foreach($value in @('NaN','Infinity','-1','0',"2`nInjected=1")){
            $script:request.timerSeconds=$value
            {Convert-DuneBrowserClientSettings -Request $script:request}|Should -Throw '*positive finite*'
        }
        $script:request.timerEnabled='false'
        {Convert-DuneBrowserClientSettings -Request $script:request}|Should -Throw '*JSON boolean*'
    }
}

Describe 'Portable client settings download' {
    It 'packages exact original bytes, BOM-preserving changes and verifiable hashes without filesystem writes' {
        $raw="[ConsoleVariables]`r`nVehicle.MaxVehiclesPerPlayer=10`r`nManual.Other=preserved`r`n"
        [byte[]]$original=@(239,187,191)+[Text.Encoding]::UTF8.GetBytes($raw)
        $request=@{mode='apply';selected=$true;approved=$true;engineEnabled=$true;directory='Selected client files';reviewedRaw=$false;download=$true;
            files=@{game=@{exists=$false;raw=''};engine=@{exists=$true;raw=$raw;bytes=[Convert]::ToBase64String($original)}};
            updates=@(@{file='engine';section='ConsoleVariables';key='Vehicle.MaxVehiclesPerPlayer';value='20'})}
        $result=Convert-DuneBrowserClientSettings -Request $request
        $result.download.filename | Should -Be 'DST-client-settings.zip'
        $memory=[IO.MemoryStream]::new([Convert]::FromBase64String($result.download.base64))
        $zip=[IO.Compression.ZipArchive]::new($memory,[IO.Compression.ZipArchiveMode]::Read)
        try{
            @($zip.Entries.FullName | Sort-Object) | Should -Be @('manifest.json','Originals/Engine.ini','README.txt','Updated/Engine.ini')
            $originalStream=$zip.GetEntry('Originals/Engine.ini').Open();$copy=[IO.MemoryStream]::new()
            try{$originalStream.CopyTo($copy);[Convert]::ToBase64String($copy.ToArray()) | Should -Be ([Convert]::ToBase64String($original))}finally{$originalStream.Dispose();$copy.Dispose()}
            $updatedStream=$zip.GetEntry('Updated/Engine.ini').Open();$updated=[IO.MemoryStream]::new()
            try{$updatedStream.CopyTo($updated);$bytes=$updated.ToArray()}finally{$updatedStream.Dispose();$updated.Dispose()}
            $bytes[0..2] | Should -Be @(239,187,191)
            $text=[Text.Encoding]::UTF8.GetString($bytes)
            $text | Should -Match 'Vehicle.MaxVehiclesPerPlayer=20'
            $text | Should -Match 'Manual.Other=preserved'
            $manifestReader=[IO.StreamReader]::new($zip.GetEntry('manifest.json').Open())
            try{$manifest=$manifestReader.ReadToEnd()|ConvertFrom-Json}finally{$manifestReader.Dispose()}
            $sha=[Security.Cryptography.SHA256]::Create()
            try{$expected=([BitConverter]::ToString($sha.ComputeHash($original))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
            $manifest.delivery | Should -Be 'manual'
            $manifest.files[0].originalSha256 | Should -Be $expected
            $manifest.files[0].updated | Should -Be 'Updated/Engine.ini'
        }finally{$zip.Dispose();$memory.Dispose()}
        $request.files.engine.raw | Should -Be $raw
    }

    It 'rejects backup bytes that disagree with the reviewed original' {
        $request=@{files=@{game=@{exists=$true;raw='reviewed';bytes=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('different'))}}}
        {New-DuneBrowserClientDownload -Request $request -Changes @{game=@{after='new'}}} | Should -Throw '*do not match*'
    }

    It 'rejects malformed original encoding rather than silently replacing text' {
        $request=@{files=@{game=@{exists=$true;raw='';bytes=[Convert]::ToBase64String([byte[]]@(255))}}}
        {New-DuneBrowserClientDownload -Request $request -Changes @{game=@{after='new'}}} | Should -Throw '*UTF-8*'
    }

    It 'does not manufacture a download for unchanged settings' {
        New-DuneBrowserClientDownload -Request @{} -Changes @{} | Should -BeNullOrEmpty
    }

    It 'requires real booleans for review approval and download delivery' {
        foreach($flag in @('download','approved','reviewedRaw')){
            $request=@{mode='apply';selected=$true;engineEnabled=$true};$request[$flag]='true'
            {Convert-DuneBrowserClientSettings -Request $request} | Should -Throw '*JSON booleans*'
        }
    }
}
