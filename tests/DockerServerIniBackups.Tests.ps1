BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'ServerIniBackups.ps1'
    function global:Invoke-DuneDockerSettingsReader {param($Request)}
    function global:Resolve-DuneRetailServerSettingsTarget {throw 'Native backups must not resolve VM storage.'}
    $script:backupPath='/srv/UserSettings/.dst-backups/UserServerCustomSettings.ini-20261108T040000Z-aaaaaaaaaaaa.bak'
    $script:bytes=[Text.Encoding]::UTF8.GetBytes("; original`r`n[Settings]`r`nValue=2`r`n")
    $script:hash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($script:bytes)).ToLowerInvariant()
}
Describe 'Native server INI backup transport' {
    BeforeEach {$script:priorBackend=$env:DST_HOSTING_BACKEND;$env:DST_HOSTING_BACKEND='docker'}
    AfterEach {$env:DST_HOSTING_BACKEND=$script:priorBackend}
    It 'lists checked backups through the owned settings service with no VM target' {
        Mock Invoke-DuneDockerSettingsReader {@{backups=@(@{path=$script:backupPath;sha256=$script:hash})}}
        (Get-DuneServerIniBackups -Ip docker).backups.Count|Should -Be 1
        Should -Invoke Invoke-DuneDockerSettingsReader -Exactly -Times 1 -ParameterFilter {$Request.action -eq 'backups.inspect'}
    }
    It 'downloads exact server before-image bytes to a relative ZIP entry without deleting' {
        Mock Invoke-DuneDockerSettingsReader {@{base64=[Convert]::ToBase64String($script:bytes)}}
        $result=Export-DuneServerIniBackups -Ip docker -Files @(@{path=$script:backupPath;sha256=$script:hash})
        $stream=[IO.MemoryStream]::new([Convert]::FromBase64String($result.base64));$zip=[IO.Compression.ZipArchive]::new($stream)
        try {
            $zip.Entries[0].FullName|Should -Be $script:backupPath.Substring(5)
            $reader=[IO.StreamReader]::new($zip.Entries[0].Open())
            try{$reader.ReadToEnd()|Should -Be ([Text.Encoding]::UTF8.GetString($script:bytes))}finally{$reader.Dispose()}
        }finally{$zip.Dispose();$stream.Dispose()}
        Should -Invoke Invoke-DuneDockerSettingsReader -Exactly -Times 1 -ParameterFilter {$Request.action -eq 'backups.read' -and $Request.sha256 -ceq $script:hash}
    }
    It 'sends exact checksum selections for deletion and refuses active and legacy paths' {
        Mock Invoke-DuneDockerSettingsReader {@{deleted=1;results=@(@{path=$script:backupPath;ok=$true})}}
        (Remove-DuneServerIniBackups -Ip docker -Files @(@{path=$script:backupPath;sha256=$script:hash})).deleted|Should -Be 1
        foreach($path in @('/srv/UserSettings/UserGame.ini','/srv/UserSettings/UserGame.ini.dstbak-123',($script:backupPath+'/../UserGame.ini'))){
            {Remove-DuneServerIniBackups -Ip docker -Files @(@{path=$path;sha256=$script:hash})}|Should -Throw '*Invalid*'
        }
        Should -Invoke Invoke-DuneDockerSettingsReader -Exactly -Times 1 -ParameterFilter {$Request.action -eq 'backups.delete-checked'}
    }
}
