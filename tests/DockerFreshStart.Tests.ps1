BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'Gameplay.ps1'
    Import-DstLib 'DockerPlayerCoordinates.ps1'
    Import-DstLib 'DockerFreshStart.ps1'
    $script:pathImplementation=(Get-Command Get-DuneDockerFreshStartPath).ScriptBlock
    function Invoke-DuneDockerManager {param($Request)}
    function Invoke-DuneSqlQuery {param($Ip,$Sql,$ReadOnly,$MaxRows,$TimeoutSec,[switch]$Bulk)}
    function Get-DuneNpeCompletionNodes { @('Fixture.Npe.One','Fixture.Npe.Two') }
}
Describe 'Native purchase snapshot storage and identity' {
    BeforeEach {
        $script:file=Join-Path $TestDrive ("snapshots/"+('a'*32)+'.json')
        if(Test-Path -LiteralPath $script:file){Remove-Item -LiteralPath $script:file}
        Mock Get-DuneDockerFreshStartPath {$script:file}
        Mock Invoke-DuneSqlQuery {
            if(-not $ReadOnly){return @{ok=$true}}
            $id=if($Sql -match 's.account_id=18::bigint'){'18'}else{'17'}
            @{ok=$true;columns=@('character_id','account_id','name','fls_id','sets','pieces','cosmetics');
              rows=@(,@('9007199254741301',$id,'Same Name',"FLS-$id",'["MTX_Keep","Earned_Omit"]','["Choam_Keep",null]','{"m_UnlockedCustomizationIds":["MTX_Cosmetic"]}'))}
        }
    }
    It 'captures paid builds with exact string identity and preserves a second account with the same display name' {
        (Invoke-DuneDockerPlayerSnapshotBuilds -AccountId 17).ok|Should -BeTrue
        (Invoke-DuneDockerPlayerSnapshotBuilds -AccountId 18).ok|Should -BeTrue
        $store=Read-DuneDockerFreshStartStore -Path $script:file
        $store.snapshots.Count|Should -Be 2
        $store.snapshots[0].character_id|Should -BeExactly '9007199254741301'
        $store.snapshots[0].account_id|Should -BeOfType [string]
        @($store.snapshots[0].building_sets)|Should -Be @('MTX_Keep')
        @($store.snapshots[0].buildable_pieces)|Should -Be @('Choam_Keep')
        $list=Get-DuneDockerFreshStartSnapshotList
        $list.Count|Should -Be 2
        $list[0].account_id|Should -Be '17'
        $list[0].saved_at|Should -BeOfType [string]
        @(Get-ChildItem -LiteralPath (Split-Path $script:file) -Filter '*.tmp').Count|Should -Be 0
    }
    It 'refuses an ambiguous name while the explicitly selected account can restore' {
        [void](Invoke-DuneDockerPlayerSnapshotBuilds -AccountId 17)
        [void](Invoke-DuneDockerPlayerSnapshotBuilds -AccountId 18)
        (Invoke-DuneDockerPlayerRestoreBuilds -Name 'Same Name').ok|Should -BeFalse
        (Invoke-DuneDockerPlayerRestoreBuilds -Name 'Same Name' -AccountId 18).ok|Should -BeTrue
        Should -Invoke Invoke-DuneSqlQuery -Times 1 -Exactly -ParameterFilter {-not $ReadOnly -and $Sql -match 'account_id=18::bigint'}
    }
    It 'preserves explicit empty purchase arrays when the character has no purchased unlocks' {
        Mock Invoke-DuneSqlQuery { @{ok=$true;columns=@('character_id','account_id','name','fls_id','sets','pieces','cosmetics');rows=@(,@('101','17','Empty Purchases','FLS-17','[]','[]',$null))} }
        (Invoke-DuneDockerPlayerSnapshotBuilds -AccountId 17).ok|Should -BeTrue
        $store=Read-DuneDockerFreshStartStore -Path $script:file
        $store.snapshots[0].building_sets.Count|Should -Be 0
        $store.snapshots[0].buildable_pieces.Count|Should -Be 0
    }
    It 'preserves a corrupt store instead of overwriting it with a fresh snapshot' {
        [void][IO.Directory]::CreateDirectory((Split-Path $script:file))
        [IO.File]::WriteAllText($script:file,'{invalid')
        $result=Invoke-DuneDockerPlayerSnapshotBuilds -AccountId 17
        $result.ok|Should -BeFalse
        $result.error|Should -Match 'could not be read'
        [IO.File]::ReadAllText($script:file)|Should -BeExactly '{invalid'
    }
    It 'rejects another project snapshot file without modifying it' {
        [void][IO.Directory]::CreateDirectory((Split-Path $script:file))
        $store=@{format=1;project_id=('b'*32);snapshots=@()}
        $original=ConvertTo-Json $store
        [IO.File]::WriteAllText($script:file,$original)
        {Read-DuneDockerFreshStartStore -Path $script:file}|Should -Throw '*could not be read*'
        [IO.File]::ReadAllText($script:file)|Should -BeExactly $original
    }
    It 'leaves the store unchanged on an identity query failure' {
        [void](Invoke-DuneDockerPlayerSnapshotBuilds -AccountId 17)
        $original=[IO.File]::ReadAllText($script:file)
        Mock Invoke-DuneSqlQuery { @{ok=$false;error='fixture identity unavailable'} }
        (Invoke-DuneDockerPlayerSnapshotBuilds -AccountId 18).ok|Should -BeFalse
        [IO.File]::ReadAllText($script:file)|Should -BeExactly $original
    }
    It 'does not report success after a restore transaction fails' {
        [void](Invoke-DuneDockerPlayerSnapshotBuilds -AccountId 17)
        Mock Invoke-DuneSqlQuery { @{ok=$false;error='fixture rollback'} } -ParameterFilter {-not $ReadOnly}
        $result=Invoke-DuneDockerPlayerRestoreBuilds -Name 'Same Name' -AccountId 17
        $result.ok|Should -BeFalse
        $result.error|Should -Match 'fixture rollback'
    }
}
Describe 'Native purchase restore transaction' {
    It 'locks exact active identity and preserves current purchases and cosmetics before verifying the entire change' {
        $sql=Get-DuneDockerFreshStartRestoreSql -AccountId 17 -Payload @{fls_id="Quote'`$dst_purchases`$";sets=@('MTX_Keep');pieces=@();cosmetics=$null;nodes=@()} -SkipNpe $false
        $sql|Should -Match 'INTO STRICT selected'
        $sql|Should -Match "selected.online_status<>'Offline'"
        $sql|Should -Match 'different account identity'
        $sql|Should -Match 'array_position\(expected_sets,entry\) IS NULL'
        $sql|Should -Match 'current_ids:=current_ids\|\|jsonb_build_array'
        $sql|Should -Match 'properties=expected_properties'
        $sql|Should -Not -Match "Quote'"
        $sql|Should -Not -Match 'INSERT INTO dune.player_tags'
    }
    It 'includes tutorial completion and verification in the same transaction only when requested' {
        $sql=Get-DuneDockerFreshStartRestoreSql -AccountId 17 -Payload @{fls_id='fixture';sets=@();pieces=@();cosmetics=$null;nodes=@('Fixture.Npe')} -SkipNpe $true
        $sql|Should -Match 'NPE.HasCompletedNPE'
        $sql|Should -Match 'No changes were saved'
        ([regex]::Matches($sql,'DO \$dst_purchases\$')).Count|Should -Be 1
        $sql|Should -Not -Match '__NPE__|__ACCOUNT__|__PAYLOAD__'
    }
}
Describe 'Native purchase store location' {
    It 'uses only a verified owned project in the persistent configuration folder' {
        Mock Invoke-DuneDockerManager { @{ok=$true;data=@{projectId=('a'*32)}} }
        $path=& $script:pathImplementation
        [IO.Path]::GetFileName($path)|Should -Be (('a'*32)+'.json')
        $path|Should -Match 'fresh-start-snapshots'
        Mock Invoke-DuneDockerManager { @{ok=$true;data=@{projectId='../other'}} }
        {& $script:pathImplementation}|Should -Throw '*could not be verified*'
    }
}
