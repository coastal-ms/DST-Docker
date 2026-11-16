BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'Config.ps1'
    Import-DstLib 'DockerSettings.ps1'
    Import-DstLib 'RetailServerSettings.ps1'
    Import-DstLib 'GameConfig.ps1'
    . (Join-Path (Get-DstRepoRoot) 'app/server/lib/Maps.ps1')
    function global:Invoke-DuneDockerManager {param($Request)}
    function global:Invoke-V6Ssh {param($Ip,$Cmd,$StdinData,$TimeoutSec);throw 'Native settings must never use SSH.'}
    function global:Invoke-WithDuneLock {param($Name,$Script);& $Script}
}

Describe 'Offline settings reads use guarded Docker management' {
    It 'keeps backup requests distinct from active-file reads' {
        Mock Invoke-DuneDockerManager {param($Request);@{ok=$true;data=@{action=$Request.action}}}
        (Invoke-DuneDockerSettingsReader -Request @{action='backups.list'}).action | Should -Be 'settings.backups.list'
        (Invoke-DuneDockerSettingsReader -Request @{action='backups.inspect'}).action | Should -Be 'settings.backups.inspect'
        {Invoke-DuneDockerSettingsReader -Request @{action='exec';file='game'}} | Should -Throw '*Unsupported*'
        Should -Invoke Invoke-DuneDockerManager -Times 0 -ParameterFilter {$Request.action -eq 'settings.read'}
    }

    It 'requests only the selected known INI and returns the helper snapshot' {
        Mock Invoke-DuneDockerManager { @{ok=$true;data=@{raw='Manual=42';revision=('a'*64)}} }
        $result=Read-DuneDockerSettingsFile -File game
        $result.raw | Should -Be 'Manual=42'
        Should -Invoke Invoke-DuneDockerManager -Times 1 -Exactly -ParameterFilter {
            $Request.action -eq 'settings.read' -and $Request.file -eq 'game' -and $Request.Count -eq 2
        }
    }
    It 'preserves the manager refusal instead of claiming that settings loaded' {
        Mock Invoke-DuneDockerManager { @{ok=$false;error='Recover the interrupted server update before starting another operation.'} }
        { Read-DuneDockerSettingsFile -File engine } | Should -Throw '*Recover the interrupted server update*'
    }
}

Describe 'Existing settings workflows use the native file transport' {
    BeforeEach {
        $script:oldBackend=$env:DST_HOSTING_BACKEND;$env:DST_HOSTING_BACKEND='docker'
        $script:raw="; manual setting`r`n[ConsoleVariables]`r`nVehicle.MaxVehiclesPerPlayer=20`r`n"
        Mock Read-DuneDockerSettingsFile {param($File);@{raw=$script:raw;revision=('a'*64);fileExists=$true}}
        Mock Write-DuneDockerSettingsFile {param($File,$Raw,$Revision,$ExpectedExists);@{revision=('b'*64);raw=$Raw}}
        Mock Get-DuneRetailStartupSyncPreference {@{enabled=$true;injectionsApplied=$true}}
        Mock Set-DuneRetailStartupSyncPreference {@{enabled=$true;injectionsApplied=$true}}
        Mock Invoke-DuneDockerManager {param($Request);
            if($Request.action -eq 'settings.backup'){return @{ok=$true;data=@{files=@($Request.files|ForEach-Object {@{file=$_;ok=$true}})}}}
            @{ok=$true;data=@{projectId=('a'*32);desiredState='stopped';services=@(@{component='game-1';state='exited'})}}
        }
    }
    AfterEach {$env:DST_HOSTING_BACKEND=$script:oldBackend}

    It 'reads exact authoritative text through the same shared INI parser' {
        $result=Get-DuneGameConfig -Ip docker
        $result.source|Should -Be 'live'
        $result.engine.raw|Should -BeExactly $script:raw
        $result.engine.effectiveByKey['Vehicle.MaxVehiclesPerPlayer']|Should -Be '20'
        Should -Invoke Read-DuneDockerSettingsFile -Times 2 -Exactly
    }

    It 'keeps manual keys while using shared managed-section editing and a current revision' {
        Save-DuneGameConfigLocked -Ip docker -Updates @(@{file='engine';section='ConsoleVariables';key='Vehicle.MaxVehiclesPerPlayer';value='21'})
        Should -Invoke Write-DuneDockerSettingsFile -Times 1 -Exactly -ParameterFilter {
            $File -eq 'engine' -and $Revision -eq ('a'*64) -and $ExpectedExists -and
            $Raw -match 'manual setting' -and $Raw -match 'Vehicle.MaxVehiclesPerPlayer=21'
        }
    }

    It 'retail snapshots count active processes rather than retained stopped containers' {
        $snapshot=Get-DuneRetailServerSettingsSnapshot -Ip docker
        $snapshot.target.stopped|Should -BeTrue
        $snapshot.target.serverPodCount|Should -Be 0
        $snapshot.fileAuthority|Should -BeTrue
    }

    It 'saves retail settings while the world is running without stopping maps' {
        Mock Invoke-DuneDockerManager {@{ok=$true;data=@{projectId=('a'*32);desiredState='running';services=@(@{component='game-1';state='running'})}}}
        {Set-DuneRetailServerSettings -Ip docker -ExpectedRevision ('a'*64) -Updates @{GatheringAmount='2'}}|Should -Not -Throw
        Should -Invoke Invoke-DuneDockerManager -Times 0 -ParameterFilter {$Request.action -in @('services.stop','services.restart')}
    }
    It 'returns the actual Docker before-image backup for the settings success message' {
        Mock Write-DuneDockerSettingsFile {@{revision=('b'*64);backup='UserServerCustomSettings.ini-20261115T120000Z-abcdef123456.bak'}}
        $result=Set-DuneRetailServerSettings -Ip docker -ExpectedRevision ('a'*64) -Updates @{GatheringAmount='2'}
        $result.backup.path|Should -Be '/srv/UserSettings/.dst-backups/UserServerCustomSettings.ini-20261115T120000Z-abcdef123456.bak'
        $result.backup.sha256|Should -Be ('a'*64)
    }

    It 'returns the selected image defaults without VM image discovery' {
        Mock Invoke-DuneDockerManager {@{ok=$true;data=@{game='stock game';engine='stock engine';source=@{pod='installed Docker image'}}}}
        (Get-DuneGameConfigDefaults -Ip docker).game|Should -Be 'stock game'
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'settings.defaults'}
    }

    It 'requires verified backups for every destination before the first save' {
        Mock Invoke-DuneDockerManager {@{ok=$true;data=@{files=@(@{file='game';ok=$true},@{file='engine';ok=$false})}}}
        {Save-DuneGameConfigLocked -Ip docker -Updates @(
            @{file='game';section='Custom';key='Manual';value='1'},
            @{file='engine';section='ConsoleVariables';key='Vehicle.MaxVehiclesPerPlayer';value='21'}
        )}|Should -Throw '*all pre-save INI backups*'
        Should -Invoke Write-DuneDockerSettingsFile -Times 0
    }

    It 'rebuilds startup variables before the shared apply-and-start workflow' {
        Mock Sync-DuneStartupConsoleVariableOverrides {@{Success=$true}}
        $result=Invoke-DuneBattlegroupRestart -Ip docker -ApplyInis -StartStopped
        $result.ok|Should -BeTrue
        Should -Invoke Sync-DuneStartupConsoleVariableOverrides -Times 1
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'services.start'}
        Should -Invoke Set-DuneRetailStartupSyncPreference -Times 1 -ParameterFilter {$Enabled -and $Applied}
        $script:DuneConfigurationExplicitApply|Should -BeFalse
    }

    It 'does not restart when startup settings cannot be rebuilt' {
        Mock Sync-DuneStartupConsoleVariableOverrides {throw 'INI read failed'}
        {Invoke-DuneBattlegroupRestart -Ip docker -ApplyInis}|Should -Throw '*INI read failed*'
        Should -Invoke Invoke-DuneDockerManager -Times 0 -ParameterFilter {$Request.action -eq 'services.restart'}
        $script:DuneConfigurationExplicitApply|Should -BeFalse
    }
}
