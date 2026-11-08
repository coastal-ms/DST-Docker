BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerPlayerTags.ps1'
    function Invoke-DuneSqlQuery {param($Ip,$Sql,$ReadOnly,$MaxRows,$TimeoutSec)}
}
Describe 'Native tag request arrays' {
    BeforeAll {
        $script:tagHandlers=@{}
        function Register-DuneRoute {param($Method,$Path,$Handler,[switch]$LocalOnly);$script:tagHandlers["$Method $Path"]=$Handler}
        function Write-DuneError {param($Response,$Status,$Message); @{status=$Status;error=$Message}}
        function Invoke-DunePlayerSetTags {param($Ip,$AccountId,[string[]]$Tags); @{tags=$Tags}}
        function Invoke-DunePlayerUpdateTags {param($Ip,$AccountId,[string[]]$Add,[string[]]$Remove); @{add=$Add;remove=$Remove}}
        . (Join-Path (Get-DstRepoRoot) 'app/server/routes/GameplayPlayers.ps1')
        . (Join-Path (Get-DstRepoRoot) 'app/server/routes/PlayersWrites.ps1')
        function Invoke-DunePlayerWriteRoute {param($Response,$Action); & $Action docker}
    }
    BeforeEach {$script:previousBackend=$env:DST_HOSTING_BACKEND;$env:DST_HOSTING_BACKEND='docker'}
    AfterEach {$env:DST_HOSTING_BACKEND=$script:previousBackend}
    It 'preserves one tag and accepts an explicit empty replacement' {
        $handler=$script:tagHandlers['POST /api/gameplay/players/tags']
        $result=& $handler $null $null @{} @{account_id=17;tags=@('Fixture.Single')}
        @($result.tags).Count|Should -Be 1
        $result.tags[0]|Should -Be 'Fixture.Single'
        $result=& $handler $null $null @{} @{account_id=17;tags=@()}
        @($result.tags).Count|Should -Be 0
    }
    It 'rejects missing and scalar replacement tags rather than clearing them' {
        $handler=$script:tagHandlers['POST /api/gameplay/players/tags']
        (& $handler $null $null @{} @{account_id=17}).status|Should -Be 400
        (& $handler $null $null @{} @{account_id=17;tags='Fixture.Scalar'}).status|Should -Be 400
    }
    It 'accepts an additions-only delta without manufacturing an empty removal tag' {
        $handler=$script:tagHandlers['POST /api/gameplay/players/update-tags']
        $result=& $handler $null $null @{} @{account_id=17;add=@('Fixture.Single')}
        $result.add[0]|Should -Be 'Fixture.Single'
        $result.remove|Should -BeNullOrEmpty
    }
    It 'rejects scalar delta inputs' {
        $handler=$script:tagHandlers['POST /api/gameplay/players/update-tags']
        (& $handler $null $null @{} @{account_id=17;add='Fixture.Scalar'}).status|Should -Be 400
    }
}
Describe 'Native character tag edits' {
    BeforeEach { Mock Invoke-DuneSqlQuery { @{ok=$true} } }
    It 'deduplicates additions while preserving case and literal data' {
        $result=Invoke-DuneDockerPlayerTags -Ip docker -AccountId 17 -Add @(' Test.Tag ','Test.Tag','test.tag',"Quote'`$dst_tags`$") -Remove @('Old.Tag','Old.Tag')
        $result.ok|Should -BeTrue
        $result.added.Count|Should -Be 3
        $result.removed.Count|Should -Be 1
        Should -Invoke Invoke-DuneSqlQuery -Times 1 -Exactly -ParameterFilter {
            -not $ReadOnly -and $Sql -match 'INTO STRICT selected' -and $Sql -match "character_state='Active' FOR UPDATE" -and
            $Sql -match 'PERFORM dune.update_player_tags' -and $Sql -match 'actual IS DISTINCT FROM expected' -and $Sql -notmatch "Quote'"
        }
    }
    It 'supports replacing the tag set with an empty set atomically' {
        $result=Invoke-DuneDockerPlayerTags -Ip docker -AccountId 17 -Add @() -Replace
        $result.ok|Should -BeTrue
        $result.tags.Count|Should -Be 0
        Should -Invoke Invoke-DuneSqlQuery -Times 1 -Exactly -ParameterFilter {$Sql -match 'NOT\(tag=ANY\(additions\)\)'}
    }
    It 'rejects an absent account, empty delta and malformed tags before SQL' {
        (Invoke-DuneDockerPlayerTags -AccountId 0 -Add @('Valid')).ok|Should -BeFalse
        (Invoke-DuneDockerPlayerTags -AccountId 17).ok|Should -BeFalse
        (Invoke-DuneDockerPlayerTags -AccountId 17 -Add @(' ')).ok|Should -BeFalse
        (Invoke-DuneDockerPlayerTags -AccountId 17 -Add @('x'*129)).ok|Should -BeFalse
        (Invoke-DuneDockerPlayerTags -AccountId 17 -Add @('x'*65) -Replace).ok|Should -BeFalse
        (Invoke-DuneDockerPlayerTags -AccountId 17 -Add @("Bad$([char]0)Tag")).ok|Should -BeFalse
        Should -Invoke Invoke-DuneSqlQuery -Times 0 -Exactly
    }
    It 'does not report success when the transaction or verification fails' {
        Mock Invoke-DuneSqlQuery { @{ok=$false;error='fixture rollback'} }
        $result=Invoke-DuneDockerPlayerTags -AccountId 17 -Add @('Valid')
        $result.ok|Should -BeFalse
        $result.error|Should -Match 'fixture rollback'
    }
}
