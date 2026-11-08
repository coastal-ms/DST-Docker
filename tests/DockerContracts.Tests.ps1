BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'Gameplay.ps1'
    Import-DstLib 'PlayersRead.ps1'
    Import-DstLib 'PlayersAdmin.ps1'
    Import-DstLib 'PlayersWrites.ps1'
    Import-DstLib 'DockerPlayerCoordinates.ps1'
    Import-DstLib 'DockerContracts.ps1'
    function Invoke-DuneSqlQuery {param($Ip,$Sql,$ReadOnly,$MaxRows,$TimeoutSec,[switch]$Bulk)}
}
Describe 'Native contract catalog payload' {
    It 'canonicalizes aliases and case variants while deduplicating contracts and completion tags' {
        $result=Get-DuneDockerContractPayload -ContractIds @('arrakeen_banquet_01','DA_CT_Arrakeen_Banquet_01')
        $result.ok|Should -BeTrue
        $result.payload.contracts.Count|Should -Be 1
        $result.payload.contracts[0]|Should -BeExactly 'DA_CT_Arrakeen_Banquet_01'
        $result.payload.short_names[0]|Should -BeExactly 'Arrakeen_Banquet_01'
        @($result.payload['add'])|Should -Contain 'Contract.Tracking.Completed.Arrakeen_Banquet_01'
    }
    It 'includes catalog skill grants remove-tags and faction floors without inventing rewards' {
        $result=Get-DuneDockerContractPayload -ContractIds @('DA_CT_Trainer_Mentat2_06','DA_CT_Fac_Atre_Rank01_04_TestLoyalty','DA_CT_Fac_Atre_Rank04_05_Skorda')
        $result.ok|Should -BeTrue
        $result.payload.skills|Should -Contain 'Skills.Key.CapstoneMentalCalculus'
        $result.payload['remove']|Should -Contain 'Contract.Tracking.FactionStory.ShowSkorda'
        ($result.payload.bumps | Where-Object name -eq Atreides).minimum|Should -BeGreaterOrEqual 250
    }
    It 'rejects mixed unknown IDs before submitting a transaction' {
        Mock Invoke-DuneSqlQuery {throw 'No query expected'}
        (Invoke-DuneDockerPlayerContracts -AccountId 17 -ContractIds @('Arrakeen_Banquet_01','unknown-fixture')).ok|Should -BeFalse
        (Invoke-DuneDockerPlayerContracts -AccountId 0 -ContractIds @('Arrakeen_Banquet_01')).ok|Should -BeFalse
        (Invoke-DuneDockerPlayerContracts -AccountId 17 -ContractIds @()).ok|Should -BeFalse
        Should -Invoke Invoke-DuneSqlQuery -Times 0 -Exactly
    }
    It 'reverses only completion tags and skills without reputation floors or prior-tag restoration' {
        $result=Get-DuneDockerContractPayload -ContractIds @('DA_CT_Fac_Atre_Rank04_05_Skorda') -Reverse
        $result.ok|Should -BeTrue
        $result.payload['add'].Count|Should -Be 0
        $result.payload.bumps.Count|Should -Be 0
        $result.payload['remove']|Should -Not -Contain 'Contract.Tracking.FactionStory.ShowSkorda'
    }
}
Describe 'Native contract atomic write' {
    It 'uses one offline transaction with tag skill standing and item/card verification' {
        $resolved=Get-DuneDockerContractPayload -ContractIds @('DA_CT_Trainer_Mentat2_06','DA_CT_Fac_Atre_Rank01_04_TestLoyalty')
        $sql=Get-DuneDockerContractSql -AccountId 17 -Payload $resolved.payload
        ([regex]::Matches($sql,'DO \$dst_contracts\$')).Count|Should -Be 1
        $sql|Should -Match 'INTO STRICT selected'
        $sql|Should -Match "selected.online_status IS DISTINCT FROM 'Offline'"
        $sql|Should -Match 'actual_tags IS DISTINCT FROM expected_tags'
        $sql|Should -Match 'components=expected_components'
        $sql|Should -Match 'GREATEST\(COALESCE\(rep,0\),component_rep,minimum_rep\)'
        $sql|Should -Match 'inv.inventory_type=29'
        $sql|Should -Match 'completed contract items could not be verified'
        $sql|Should -Match 'card cleanup could not be verified'
        $sql|Should -Not -Match '__[A-Z_]+__|floor_entry_id'
    }
    It 'preserves reputation active items and invested skill blocks during reversal' {
        $resolved=Get-DuneDockerContractPayload -ContractIds @('DA_CT_Trainer_Mentat2_06') -Reverse
        $sql=Get-DuneDockerContractSql -AccountId 17 -Payload $resolved.payload -Reverse
        $sql|Should -Match 'IF spent<=1 THEN modules:=modules-skill_key'
        $sql|Should -Not -Match 'DELETE FROM dune.items|set_player_faction_reputation|UPDATE dune.actors'
    }
    It 'does not report completion after a failed transaction' {
        Mock Invoke-DuneSqlQuery { @{ok=$false;error='fixture rollback'} }
        $result=Invoke-DuneDockerPlayerContracts -AccountId 17 -ContractIds @('Arrakeen_Banquet_01')
        $result.ok|Should -BeFalse
        $result.error|Should -Match 'fixture rollback'
    }
}
