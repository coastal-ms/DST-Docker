BeforeAll {
    . "$PSScriptRoot\_TestHelpers.ps1"
    function Get-DuneDbContext {throw 'Mock required'}
    function Invoke-DuneSqlQuery {param($Ip,$Sql,$ReadOnly,$MaxRows,$TimeoutSec) throw 'Mock required'}
    function Read-DuneBotConfig {throw 'Unqualified Docker bot adapter must not run'}
    Import-DstLib 'Gameplay.ps1'
}
Describe 'Native market read transport' {
    BeforeEach {$script:previousBackend=$env:DST_HOSTING_BACKEND;$env:DST_HOSTING_BACKEND='docker'}
    AfterEach {$env:DST_HOSTING_BACKEND=$script:previousBackend}
    It 'reports database availability independently of unqualified vendor automation' {
        Mock Get-DuneDbContext {@{ok=$true;ip='docker'}}
        $result=Get-DuneGameplayStatus
        $result.db_available|Should -BeTrue;$result.source|Should -Be live
        $result.bot_configured|Should -BeFalse;$result.bot_reachable|Should -BeFalse
    }
    It 'uses native read-only SQL and preserves integer pricing and stock' {
        Mock Invoke-DuneSqlQuery {@{ok=$true;columns=@('id','template_id','is_npc_order','owner_name','item_price','stock','quality');rows=@(,@('12345678901234567','FixtureTemplate','t','Fixture Vendor','17','42','3'))}}
        $result=Get-DuneMarketListingsLive -Ip docker -TemplateId "Fixture'Template"
        $result.ok|Should -BeTrue;$result.listings[0].price|Should -Be 170;$result.listings[0].stock|Should -Be 42
        $result.listings[0].order_id|Should -Be '12345678901234567'
        Should -Invoke Invoke-DuneSqlQuery -Times 1 -ParameterFilter {$Ip -eq 'docker' -and $ReadOnly -eq $true -and $Sql.Contains("Fixture''Template")}
    }
    It 'returns an unavailable live result when native SQL fails' {
        Mock Invoke-DuneSqlQuery {@{ok=$false;error='Native database unavailable'}}
        $result=Get-DuneMarketSalesLive -Ip docker
        $result.ok|Should -BeFalse;$result.error|Should -Be 'Native database unavailable'
    }
}
