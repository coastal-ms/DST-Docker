BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerManager.ps1'
}
Describe 'Windows Explorer mirror path comes from the WSL host marker' {
    BeforeEach {
        $script:marker=Join-Path $TestDrive 'platform.json'
        @{platform='wsl';distribution='Ubuntu'}|ConvertTo-Json|Set-Content -LiteralPath $script:marker
    }
    It 'copies a real UNC path rather than merely replacing Linux slashes' {
        Get-DuneDockerWindowsMirrorPath -Folder '/home/coastal/backups/world-one' -MarkerPath $script:marker|Should -Be '\\wsl.localhost\Ubuntu\home\coastal\backups\world-one'
    }
    It 'does not guess a distribution when host metadata is absent or native Linux' {
        Get-DuneDockerWindowsMirrorPath -Folder '/home/test/copies' -MarkerPath (Join-Path $TestDrive 'absent.json')|Should -Be ''
        @{platform='linux';distribution='Ubuntu'}|ConvertTo-Json|Set-Content -LiteralPath $script:marker
        Get-DuneDockerWindowsMirrorPath -Folder '/home/test/copies' -MarkerPath $script:marker|Should -Be ''
    }
    It 'rejects traversal, relative paths and Windows-invalid path names' {
        foreach($folder in @('../copies','/home/../copies','/home/./copies','/home/test:other','/home/test\other','//server/copies','')) {
            Get-DuneDockerWindowsMirrorPath -Folder $folder -MarkerPath $script:marker|Should -Be ''
        }
    }
    It 'never treats a malformed distribution as a UNC host or share' {
        @{platform='wsl';distribution='Ubuntu\other'}|ConvertTo-Json|Set-Content -LiteralPath $script:marker
        Get-DuneDockerWindowsMirrorPath -Folder '/home/test/copies' -MarkerPath $script:marker|Should -Be ''
    }
}
