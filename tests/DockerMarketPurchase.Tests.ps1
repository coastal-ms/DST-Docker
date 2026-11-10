BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'Gameplay.ps1'
    Import-DstLib 'DockerMarket.ps1'
    Import-DstLib 'GameplayBot.ps1'
    function Invoke-DuneSqlQuery { param($Ip,$Sql,$ReadOnly,$MaxRows,$TimeoutSec); throw 'SQL must be mocked.' }
    $script:purchase=@{Ip='docker';Ident=@{exchangeId=11;accessPointId=12;ownerId=13};OrderId=14;SellerId=15;ItemId=16;TemplateId='Fixture';UnitPrice=83;Stack=23;OrderExpiry=1900000000}
}
Describe 'Native market purchase result and input boundaries' {
    BeforeEach { Mock Invoke-DuneSqlQuery { @{ok=$true;columns=@('purchased');rows=@(,@('1'))} } }
    It 'reports a proven committed purchase only for an exact one result' {
        $result=Invoke-DuneDockerBotPurchase @script:purchase
        $result.ok | Should -BeTrue
        $result.purchased | Should -BeTrue
        Should -Invoke Invoke-DuneSqlQuery -Times 1 -ParameterFilter {-not $ReadOnly -and $MaxRows -eq 1 -and $TimeoutSec -eq 45}
    }
    It 'reports an obsolete listing or insufficient balance as a skipped purchase' {
        Mock Invoke-DuneSqlQuery { @{ok=$true;columns=@('purchased');rows=@(,@('0'))} }
        $result=Invoke-DuneDockerBotPurchase @script:purchase
        $result.ok | Should -BeTrue
        $result.purchased | Should -BeFalse
    }
    It 'rejects unreadable results rather than claiming a purchase' -TestCases @(@{Value=''},@{Value='2'},@{Value='unknown'}) {
        param($Value)
        Mock Invoke-DuneSqlQuery { @{ok=$true;columns=@('purchased');rows=@(,@($Value))} }
        (Invoke-DuneDockerBotPurchase @script:purchase).ok | Should -BeFalse
    }
    It 'preserves transaction failures as failures' {
        Mock Invoke-DuneSqlQuery { @{ok=$false;error='transaction rolled back'} }
        $result=Invoke-DuneDockerBotPurchase @script:purchase
        $result.ok | Should -BeFalse
        $result.error | Should -Be 'transaction rolled back'
    }
    It 'rejects invalid identities and overflowing costs before SQL' {
        $invalid=@{};foreach($key in $script:purchase.Keys){$invalid[$key]=$script:purchase[$key]}
        $invalid.SellerId=13
        (Invoke-DuneDockerBotPurchase @invalid).ok | Should -BeFalse
        $invalid.SellerId=15;$invalid.UnitPrice=[long]::MaxValue;$invalid.Stack=[long]::MaxValue
        (Invoke-DuneDockerBotPurchase @invalid).ok | Should -BeFalse
        $invalid.UnitPrice=-1;$invalid.Stack=23
        (Invoke-DuneDockerBotPurchase @invalid).ok | Should -BeFalse
        Should -Invoke Invoke-DuneSqlQuery -Times 0
    }
}

Describe 'Market scalar read intent' {
    BeforeEach {Mock Invoke-DuneSqlQuery { @{ok=$true;columns=@('id');rows=@(,@('17'))} }}
    It 'keeps scalar observations read-only by default' {
        (Get-DuneBotScalar -Ip docker -Sql 'SELECT 17').value | Should -Be '17'
        Should -Invoke Invoke-DuneSqlQuery -Times 1 -ParameterFilter {$ReadOnly -eq $true}
    }
    It 'allows a live caller to initialize an inventory explicitly' {
        (Get-DuneBotScalar -Ip docker -Sql 'SELECT dune.get_exchange_inventory_id(17)' -ReadOnly $false).ok | Should -BeTrue
        Should -Invoke Invoke-DuneSqlQuery -Times 1 -ParameterFilter {$ReadOnly -eq $false}
    }
}
