BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerBackups.ps1'
    . (Join-Path (Get-DstRepoRoot) 'app/server/lib/BackupSchedule.ps1')
    $script:BackupOldBackend=$env:DST_HOSTING_BACKEND
    function Invoke-DuneDockerManager {param($Request) throw 'Mock required'}
}
AfterAll {$env:DST_HOSTING_BACKEND=$script:BackupOldBackend}
Describe 'Docker backup adapters' {
    BeforeEach {
        $env:DST_HOSTING_BACKEND='docker'
        Mock Invoke-V6Ssh {throw 'Docker must not use SSH'}
        Mock Invoke-DuneDockerManager {param($Request)
            switch($Request.action){
                'status' {@{ok=$true;data=@{projectId=('a'*32);backups=@(@{id=('b'*32);name='backup-12345678-abcdef12.dump';phase='completed'})}}}
                'backups.schedule.get' {@{ok=$true;data=@{preset='Hourly';vmTimezone='UTC';crondRunning=$true}}}
                'backups.schedule.set' {@{ok=$true;data=@{preset=$Request.preset}}}
                'backups.history' {@{ok=$true;data=@{recent=@();total=0}}}
                'backups.jobs' {@{ok=$true;data=@{jobs=@(@{name='owned-job';createdAt=1700000000;state='exited'},@{name='running-job';createdAt=1700000001;state='running'})}}}
                'backups.delete' {@{ok=$true;data=@{operation=@{id=('c'*32)}}}}
                default {throw 'Unexpected Docker action'}
            }
        }
    }
    It 'reads schedule and history even when the maps and database are stopped' {
        (Get-DuneBackupContext).ip|Should -Be 'docker'
        (Get-DuneBackupSchedule -Ip docker).preset|Should -Be 'Hourly'
        (Get-DuneBackupHistory -Ip docker -Recent 200).total|Should -Be 0
        Should -Invoke Invoke-V6Ssh -Times 0
    }
    It 'saves retention through the native typed control plane' {
        (Set-DuneBackupSchedule -Ip docker -Preset Every6Hours -KeepLast 8 -KeepLastPods 12 -KeepDaysPods 7).ok|Should -BeTrue
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'backups.schedule.set' -and $Request.keepLast -eq 8 -and $Request.keepLastPods -eq 12 -and $Request.keepDaysPods -eq 7}
        Should -Invoke Invoke-V6Ssh -Times 0
    }
    It 'lists only terminal helper jobs without pretending they are successful' {
        $jobs=@(Get-DuneBackupDumpPods -Ip docker)
        $jobs.Count|Should -Be 1
        $jobs[0].phase|Should -Be 'exited'
        $jobs[0].nameTimestamp|Should -Match '^2023-'
    }
    It 'resolves exact recorded paths and reports deletion as pending' {
        $result=Remove-DuneBackupFiles -Ip docker -Paths '/backups/backup-12345678-abcdef12.dump'
        $result.pending|Should -BeTrue
        $result.deleted.Count|Should -Be 0
        Should -Invoke Invoke-DuneDockerManager -Times 1 -ParameterFilter {$Request.action -eq 'backups.delete' -and $Request.backupIds[0] -eq ('b'*32)}
        {Remove-DuneBackupFiles -Ip docker -Paths '/backups/../other.dump'}|Should -Throw
        Should -Invoke Invoke-V6Ssh -Times 0
    }
}
Describe 'Bounded browser database backup uploads' {
    BeforeAll { . (Join-Path (Get-DstRepoRoot) 'app/server/lib/DockerBackups.ps1') }
    It 'keeps the original filename as metadata and rejects path-like names before creating files' {
        $bytes=[Text.Encoding]::UTF8.GetBytes('PGDMPfixture-data')
        $directory=Join-Path $TestDrive 'named-upload'
        $stream=[IO.MemoryStream]::new($bytes)
        try{$result=Receive-DuneDockerBackupUpload -Stream $stream -Length $bytes.Length -TrustedSource $true -OriginalFilename 'My world 100%.backup' -Directory $directory}finally{$stream.Dispose()}
        $result.originalFilename|Should -BeExactly 'My world 100%.backup'
        @(Get-ChildItem $directory).Name|Should -BeExactly ($result.uploadId+'.upload')
        foreach($name in @('../world.backup','C:\world.backup',"bad`nname",('.'*256))){
            $stream=[IO.MemoryStream]::new($bytes)
            try{{Receive-DuneDockerBackupUpload -Stream $stream -Length $bytes.Length -TrustedSource $true -OriginalFilename $name -Directory (Join-Path $TestDrive 'invalid-name')}|Should -Throw}finally{$stream.Dispose()}
        }
        Test-Path (Join-Path $TestDrive 'invalid-name')|Should -BeFalse
    }
    It 'stores exact bytes with a stable checksum and an internal identity' {
        $bytes=[Text.Encoding]::UTF8.GetBytes('PGDMPfixture-data')
        $stream=[IO.MemoryStream]::new($bytes)
        $directory=Join-Path $TestDrive 'upload-exact'
        try{$result=Receive-DuneDockerBackupUpload -Stream $stream -Length $bytes.Length -TrustedSource $true -Directory $directory}finally{$stream.Dispose()}
        $result.uploadId|Should -Match '^[a-f0-9]{32}$'
        $result.bytes|Should -Be $bytes.Length
        $result.sha256|Should -Be ([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant())
        [IO.File]::ReadAllBytes((Join-Path $directory ($result.uploadId+'.upload')))|Should -Be $bytes
        @(Get-ChildItem $directory).Count|Should -Be 1
    }
    It 'rejects untrusted sources, scripts and truncated streams without leaving a partial backup' {
        foreach($case in @(@{text='PGDMPdata';length=9;trusted=$false},@{text='SELECT 1';length=8;trusted=$true},@{text='PGDMPshort';length=99;trusted=$true})){
            $directory=Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
            $stream=[IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($case.text))
            try{{Receive-DuneDockerBackupUpload -Stream $stream -Length $case.length -TrustedSource $case.trusted -Directory $directory}|Should -Throw}finally{$stream.Dispose()}
            @(Get-ChildItem $directory -ErrorAction SilentlyContinue).Count|Should -Be 0
        }
    }
}
Describe 'Completed upload cache retention' {
    BeforeAll { . (Join-Path (Get-DstRepoRoot) 'app/server/lib/DockerBackups.ps1') }
    It 'removes terminal and deleted upload copies while preserving active uploads' {
        $directory=Join-Path $TestDrive 'cache-terminal';[void][IO.Directory]::CreateDirectory($directory)
        foreach($id in @(('a'*32),('b'*32),('c'*32))){[IO.File]::WriteAllText((Join-Path $directory ($id+'.upload')),'fixture')}
        Mock Get-DuneDockerBackupData {@{operation=@{phase='completed'};backups=@(@{uploadId=('a'*32);phase='completed'},@{uploadId=('b'*32);phase='deleted'},@{uploadId=('c'*32);phase='running'})}}
        Remove-DuneDockerBackupUploadCache -Directory $directory
        @(Get-ChildItem $directory).Name|Should -BeExactly (('c'*32)+'.upload')
    }
}
