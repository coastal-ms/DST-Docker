BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerChat.ps1'
    Import-DstLib 'ChatCommands.ps1'
    function Invoke-DuneDockerManager {param($Request)}
    function New-DuneSchedulerInitialSessionState {param($ServerDir,[switch]$DeferLibraryLoad)}
    function Invoke-WithDuneLock {param($Name,$Script); & $Script}
}

Describe 'Native chat queue dispatch' {
    BeforeEach { $script:previousBackend=$env:DST_HOSTING_BACKEND;$env:DST_HOSTING_BACKEND='docker' }
    AfterEach { $env:DST_HOSTING_BACKEND=$script:previousBackend }
    It 'uses only typed declare delete and bounded drain requests' {
        Mock Read-DuneChatCommandsState { @{enabled=$true;channels=@('Proximity');commands=@{water=@{enabled=$true}}} }
        Mock Invoke-DuneDockerManager { @{ok=$true;data=@{messages=@('fixture');skipped=$false}} }
        (Initialize-DuneChatCommandQueue -Ip docker).ok|Should -BeTrue
        (Remove-DuneChatCommandQueue -Ip docker).ok|Should -BeTrue
        $drain=Get-DuneChatCommandMessages -Ip docker -Max 7
        $drain.messages|Should -Be @('fixture')
        Should -Invoke Invoke-DuneDockerManager -Times 1 -Exactly -ParameterFilter {$Request.action -eq 'chat.queue.declare'}
        Should -Invoke Invoke-DuneDockerManager -Times 1 -Exactly -ParameterFilter {$Request.action -eq 'chat.queue.delete'}
        Should -Invoke Invoke-DuneDockerManager -Times 1 -Exactly -ParameterFilter {$Request.action -eq 'chat.queue.drain' -and $Request.maximum -eq 7}
    }
    It 'reports a rejected broker request without returning chat messages' {
        Mock Invoke-DuneDockerManager { @{ok=$false;error='Server operation pending.'} }
        $result=Get-DuneChatCommandMessages -Ip docker
        $result.ok|Should -BeFalse
        $result.message|Should -Be 'Server operation pending.'
        $result.messages.Count|Should -Be 0
    }
    It 'does no broker or database work when chat commands are disabled' {
        Mock Read-DuneChatCommandsState { @{enabled=$false} }
        Mock Invoke-DuneDockerManager { throw 'Off must not contact the manager.' }
        (Invoke-DuneChatCommandTick).enabled|Should -BeFalse
        Should -Invoke Invoke-DuneDockerManager -Times 0 -Exactly
    }
    It 'checks the latest Off state before a stale listener can redeclare its queue' {
        Mock Read-DuneChatCommandsState { @{enabled=$false} }
        Mock Invoke-DuneDockerManager { @{ok=$true;data=@{messages=@();skipped=$false}} }
        (Initialize-DuneChatCommandQueue -Ip docker).ok|Should -BeTrue
        Should -Invoke Invoke-DuneDockerManager -Times 1 -Exactly -ParameterFilter {$Request.action -eq 'chat.queue.delete'}
        Should -Invoke Invoke-DuneDockerManager -Times 0 -Exactly -ParameterFilter {$Request.action -eq 'chat.queue.declare'}
    }
    It 'keeps the default Off if the settings file was removed during a running tick' {
        Mock Get-DuneChatCommandsStatePath { Join-Path $TestDrive 'chat-removed-during-tick.json' }
        $stale=New-DuneChatCommandsDefault;$stale.enabled=$true;$stale.cooldowns['fixture']='2026-11-08T08:00:00Z'
        Save-DuneChatCommandsState -State $stale -RuntimeOnly|Should -BeTrue
        (Read-DuneChatCommandsState).enabled|Should -BeFalse
        (Read-DuneChatCommandsState).cooldowns['fixture']|Should -Be '2026-11-08T08:00:00Z'
    }
    It 'does not interpret an empty native channel selection as all channels' {
        Mock Get-DuneChatCommandsStatePath { Join-Path $TestDrive 'chat-no-channels.json' }
        $state=New-DuneChatCommandsDefault;$state.enabled=$true;$state.commands.water.enabled=$true;$state.channels=@()
        Save-DuneChatCommandsState -State $state|Should -BeTrue
        $read=Read-DuneChatCommandsState
        $read.channels.Count|Should -Be 0
        (Test-DuneChatCommandsReady -State $read).reason|Should -Be 'no-channels-enabled'
    }
    It 'keeps a newer Off setting while a running tick saves its cooldowns' {
        Mock Get-DuneChatCommandsStatePath { Join-Path $TestDrive 'chat-off-race.json' }
        $initial=New-DuneChatCommandsDefault;$initial.enabled=$true
        Save-DuneChatCommandsState -State $initial|Should -BeTrue
        $tick=Read-DuneChatCommandsState
        $off=Read-DuneChatCommandsState;$off.enabled=$false;$off.commands.water.enabled=$false
        Save-DuneChatCommandsState -State $off|Should -BeTrue
        $tick.cooldowns['fixture:water']='2026-11-08T08:00:00Z'
        Save-DuneChatCommandsState -State $tick -RuntimeOnly|Should -BeTrue
        $final=Read-DuneChatCommandsState
        $final.enabled|Should -BeFalse
        $final.cooldowns['fixture:water']|Should -Be '2026-11-08T08:00:00Z'
        $staleSettings=$initial;$staleSettings.replyTitle='Changed title'
        Save-DuneChatCommandsState -State $staleSettings|Should -BeTrue
        (Read-DuneChatCommandsState).cooldowns['fixture:water']|Should -Be '2026-11-08T08:00:00Z'
        (Read-DuneChatCommandsState).replyTitle|Should -Be 'Changed title'
    }
}

Describe 'Native chat scheduler lifetime' {
    It 'waits for HTTP readiness runs once per scheduler and stops cleanly' {
        $folder=Join-Path $TestDrive 'chat-scheduler';$null=New-Item -ItemType Directory -Path $folder
        $ticks=Join-Path $folder 'ticks.txt';$source=Join-Path $folder 'fixture.ps1'
        [IO.File]::WriteAllText((Join-Path $folder 'HttpServer.ps1'),'# Isolated scheduler fixture')
        [IO.File]::WriteAllText($source,("function Invoke-DuneChatCommandTick { [IO.File]::AppendAllText('"+$ticks.Replace("'","''")+"','tick'+[Environment]::NewLine) }; function Get-DuneChatCommandPollSeconds { 1 }"))
        Mock New-DuneSchedulerInitialSessionState {
            $iss=[Management.Automation.Runspaces.InitialSessionState]::CreateDefault()
            $iss.Variables.Add([Management.Automation.Runspaces.SessionStateVariableEntry]::new('DuneSchedulerStartupScripts',@($source),''))
            $iss.Variables.Add([Management.Automation.Runspaces.SessionStateVariableEntry]::new('DuneSchedulerLogPath','',''))
            return $iss
        }
        $ready=[Threading.ManualResetEventSlim]::new($false)
        try {
            Start-DuneDockerChatScheduler -ServerDir $folder -HttpReady $ready
            $handle=$script:DuneDockerChatScheduler.handle
            Start-DuneDockerChatScheduler -ServerDir $folder -HttpReady $ready
            $script:DuneDockerChatScheduler.handle|Should -Be $handle
            Test-Path $ticks|Should -BeFalse
            $ready.Set();$deadline=[DateTime]::UtcNow.AddSeconds(5)
            while(-not(Test-Path $ticks) -and [DateTime]::UtcNow -lt $deadline){Start-Sleep -Milliseconds 30}
            Test-Path $ticks|Should -BeTrue
            Stop-DuneDockerChatScheduler|Should -BeTrue
            $count=@(Get-Content $ticks).Count;Start-Sleep -Milliseconds 100
            @(Get-Content $ticks).Count|Should -Be $count
            $script:DuneDockerChatScheduler|Should -BeNullOrEmpty
        } finally { $null=Stop-DuneDockerChatScheduler;$ready.Dispose() }
    }
}
