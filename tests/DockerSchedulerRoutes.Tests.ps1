BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'RestartSchedule.ps1'
    $script:handlers=@{}
    function Register-DuneRoute {param($Method,$Path,$Handler);$script:handlers["$Method $Path"]=$Handler}
    . (Join-Path (Get-DstRepoRoot) 'app/server/routes/RestartSchedule.ps1')
    function global:Get-DuneServerName {param([switch]$CachedOnly);'Fixture'}
    function global:Write-DuneJson {param($Response,$Body)}
    function global:Write-DuneError {param($Response,$Status,$Message)}
}
Describe 'Native schedule route validation and notification preview' {
    BeforeEach {
        $script:oldBackend=$env:DST_HOSTING_BACKEND;$env:DST_HOSTING_BACKEND='docker'
        Mock Write-DuneJson {}
        Mock Write-DuneError {}
        Mock Send-DuneDiscordWebhook {@{ok=$true}}
        Mock Send-DuneDiscordEmbed {@{ok=$true}}
        Mock Get-DuneRestartSchedule {
            $value=Get-DuneRestartScheduleDefault
            $value.discordWebhookUrl='https://discord.com/api/webhooks/123456789012345678/fixture_token_not_real'
            return $value
        }
    }
    AfterEach {$env:DST_HOSTING_BACKEND=$script:oldBackend}
    It 'uses the existing preview helper without transmitting a real message' {
        & $script:handlers['POST /api/restart-schedule/test-discord'] $null $null @{} @{}
        Should -Invoke Send-DuneDiscordWebhook -Times 1
        Should -Invoke Write-DuneJson -Times 1 -ParameterFilter {$Body.ok -eq $true}
    }
    It 'rejects a non-Discord destination before any notification helper is called' {
        & $script:handlers['POST /api/restart-schedule/test-discord'] $null $null @{} @{discordWebhookUrl='https://localhost/private'}
        Should -Invoke Write-DuneError -Times 1 -ParameterFilter {$Status -eq 400}
        Should -Invoke Send-DuneDiscordWebhook -Times 0
        Should -Invoke Send-DuneDiscordEmbed -Times 0
    }
    It 'rejects string booleans instead of accidentally enabling a schedule' {
        & $script:handlers['PUT /api/restart-schedule'] $null $null @{} @{enabled='false';time='04:00'}
        Should -Invoke Write-DuneError -Times 1 -ParameterFilter {$Status -eq 400 -and $Message -match 'JSON boolean'}
    }
}
