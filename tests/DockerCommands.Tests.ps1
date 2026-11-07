BeforeAll {
    . "$PSScriptRoot\_TestHelpers.ps1"
    Import-DstLib 'Commands.ps1'
}
Describe 'Docker command catalogue and saved layout' {
    BeforeEach {
        $script:savedBackend=$env:DST_HOSTING_BACKEND
        $env:DST_HOSTING_BACKEND='docker'
        Mock Get-DuneCommandOrderFile { Join-Path $TestDrive 'button-order.json' }
        Remove-Item (Join-Path $TestDrive 'button-order.json') -ErrorAction SilentlyContinue
    }
    AfterEach {$env:DST_HOSTING_BACKEND=$script:savedBackend}
    It 'provides one canonical action with native labels and three flat default sections' {
        $commands=@(Get-DuneCommandCatalogue)
        $commands.Count | Should -Be 8
        @($commands | Where-Object {$_.Name -in @('startup','shutdown','reboot','start-vm','ssh')}).Count | Should -Be 0
        @($commands | Where-Object {$_.Mode -ne 'Docker' -or $_.Requires -ne 'none'}).Count | Should -Be 0
        $layout=Get-DuneCommandLayout
        ($layout.sectionNames -join '|') | Should -Be 'Battlegroup|Server updates|Tools'
        ($layout.sections[0] -join '|') | Should -Be 'start|stop|restart|apply-inis'
        ($layout.sections[1] -join '|') | Should -Be 'update|update-with-tanks'
        ($layout.sections[2] -join '|') | Should -Be 'logs-export|operator-logs-export'
        ($layout.sections[0][0] -is [string]) | Should -BeTrue
        (Get-DuneCommandByName 'start').Mode | Should -Be 'Console'
    }
    It 'preserves custom names and placements while canonicalizing legacy aliases and removing unsupported cards' {
        $sections=@(@(),@(),@());$sections[0]=@('startup','start','start-vm');$sections[1]=@('shutdown');$sections[2]=@('reboot','ssh')
        Save-DuneCommandLayout -SectionNames @('My start','My stop','My tools') -Sections $sections
        $layout=Get-DuneCommandLayout
        ($layout.sectionNames -join '|') | Should -Be 'My start|My stop|My tools'
        $layout.sections[0] | Should -Contain 'start'
        $layout.sections[1] | Should -Contain 'stop'
        $layout.sections[2] | Should -Contain 'restart'
        $all=@($layout.sections | ForEach-Object {$_})
        $all.Count | Should -Be 8
        $all | Should -Not -Contain 'ssh'
        $all | Should -Not -Contain 'start-vm'
        $layout.sections[1] | Should -Contain 'update'
    }
    It 'reads old saved layouts without overwriting them and retires only the old default headings' {
        $path=Get-DuneCommandOrderFile
        $raw='{"version":3,"sectionNames":["VM","Battlegroup","Tools"],"sections":[["startup","start-vm"],["shutdown"],["reboot"]]}'
        Set-Content $path $raw
        $layout=Get-DuneCommandLayout
        ($layout.sectionNames -join '|') | Should -Be 'Battlegroup|Server updates|Tools'
        $layout.sections[0] | Should -Contain 'start'
        $layout.sections[1] | Should -Contain 'stop'
        $layout.sections[2] | Should -Contain 'restart'
        (Get-Content $path -Raw).Trim() | Should -Be $raw
    }
    It 'keeps the Windows catalogue and defaults intact after Docker projection' {
        [void](Get-DuneCommandCatalogue)
        $env:DST_HOSTING_BACKEND=''
        @((Get-DuneCommandCatalogue) | Where-Object {$_.Name -eq 'start-vm'}).Count | Should -Be 1
        @((Get-DuneCommandCatalogue) | Where-Object {$_.Name -eq 'ssh'}).Count | Should -Be 1
        ((Get-DuneDefaultCommandLayout).sectionNames -join '|') | Should -Be 'VM|Battlegroup|Tools'
    }
}
