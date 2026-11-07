BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerConsole.ps1'
}
Describe 'Persistent Docker console port' {
    It 'defaults a new installation to8088 without creating settings' {
        $path=Join-Path $TestDrive 'new/console.json'
        Get-DuneDockerConsolePort -Path $path|Should -Be 8088
        Test-Path $path|Should -BeFalse
    }
    It 'persists a chosen port through independent reads and subsequent changes' {
        $path=Join-Path $TestDrive 'saved/console.json'
        Set-DuneDockerConsolePort -Path $path -Port 9090
        Get-DuneDockerConsolePort -Path $path|Should -Be 9090
        Set-DuneDockerConsolePort -Path $path -Port 8088
        Get-DuneDockerConsolePort -Path $path|Should -Be 8088
        @(Get-ChildItem (Split-Path $path) -Force).Count|Should -Be 1
    }
    It 'refuses corrupt or untyped saved values instead of choosing a surprise port' {
        $path=Join-Path $TestDrive 'bad.json'
        foreach($raw in @('{','{"port":true}','{"port":"9090"}','{"port":80}','{"port":65536}','{"port":8088.5}')){
            [IO.File]::WriteAllText($path,$raw)
            {Get-DuneDockerConsolePort -Path $path}|Should -Throw
            [IO.File]::ReadAllText($path)|Should -BeExactly $raw
        }
    }
}
