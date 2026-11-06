BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'Config.ps1'
    Import-DstLib 'GameConfig.ps1'
    Import-DstLib 'DockerMaps.ps1'
    Import-DstLib 'Database.ps1'
    function global:Invoke-DuneDockerManager {param($Request)}
    function global:Read-DuneDockerSettingsFile {param($File)}
    function global:Invoke-DuneDockerSqlRaw {param($Sql,$TimeoutSec,$Csv,$Detailed,$ReadOnly)}
    function global:ConvertTo-DuneRowMaps {param($Result);return $Result.rows}
}

Describe 'Native specialized settings retain shared behavior' {
    BeforeEach {
        $script:oldBackend=$env:DST_HOSTING_BACKEND;$env:DST_HOSTING_BACKEND='docker'
        Mock Invoke-DuneDockerSqlRaw {'ok'}
    }
    AfterEach {$env:DST_HOSTING_BACKEND=$script:oldBackend}

    It 'keeps raw reads read-only while allowing the existing bulk-write transport to write' {
        Invoke-DuneSqlRaw -Ip docker -Sql 'SELECT 1'|Should -Be 'ok'
        Invoke-DuneSqlRawStdin -Ip docker -Sql 'CREATE FUNCTION fixture() RETURNS int LANGUAGE sql AS $$SELECT 1$$;'|Should -Be 'ok'
        Should -Invoke Invoke-DuneDockerSqlRaw -Times 1 -ParameterFilter {$Sql -eq 'SELECT 1' -and -not $PSBoundParameters.ContainsKey('ReadOnly')}
        Should -Invoke Invoke-DuneDockerSqlRaw -Times 1 -ParameterFilter {$Sql -like 'CREATE FUNCTION*' -and $ReadOnly -eq $false}
    }

    It 'only accepts the authoritative native Game.ini for time-of-day staging' {
        Mock Resolve-DuneGameConfigPaths {@{source='live';authoritative=$true;game='/srv/UserSettings/UserGame.ini'}}
        Mock Read-DuneDockerSettingsFile {@{fileExists=$true;raw="[Manual]`r`nKey=preserved`r`n"}}
        $target=Resolve-DuneTwilightLiveGameConfigTarget -Ip docker
        (Read-DuneTwilightLiveGameConfig -Ip docker -Path $target.game)|Should -Match 'Key=preserved'
        Mock Resolve-DuneGameConfigPaths {@{source='live';authoritative=$true;game='/foreign/UserGame.ini'}}
        {Resolve-DuneTwilightLiveGameConfigTarget -Ip docker}|Should -Throw '*authoritative Docker*'
        {Read-DuneTwilightLiveGameConfig -Ip docker -Path '/foreign/UserGame.ini'}|Should -Throw '*Unsupported*'
    }

    It 'does not substitute stock settings when the manually managed game file is absent' {
        Mock Read-DuneDockerSettingsFile {@{fileExists=$false;raw=''}}
        {Read-DuneTwilightLiveGameConfig -Ip docker -Path '/srv/UserSettings/UserGame.ini'}|Should -Throw '*missing*'
    }

    It 'returns only active Deep Desert instances and resolves their real database dimensions' {
        Mock Invoke-DuneDockerManager {@{ok=$true;data=@{projectId=('a'*32);profile=@{name='Fixture'};
            plan=@{games=@(@{partition=8;map='DeepDesert_1';gamePort=28784},@{partition=12;map='DeepDesert_1';gamePort=28788},@{partition=1;map='Survival_1'})};
            services=@(@{component='game-8';state='running';gameReady=$true},@{component='game-12';state='exited'})}}}
        Mock Invoke-DuneSqlQuery {@{ok=$true;rows=@(@{partition_id=8;dimension_index=2},@{partition_id=12;dimension_index=5})}}
        $result=Get-DuneDockerDeepDesertInstances
        @($result.Instances).Count|Should -Be 1
        $result.Instances[0].Dimension|Should -Be 2
        $result.Instances[0].Ready|Should -BeTrue
        @($result.ConfiguredPartitionIds)|Should -Be @(8,12)
    }

    It 'fails closed when an active native partition is no longer present in the database' {
        Mock Invoke-DuneDockerManager {@{ok=$true;data=@{plan=@{games=@(@{partition=8;map='DeepDesert_1'})};services=@(@{component='game-8';state='running'})}}}
        Mock Invoke-DuneSqlQuery {@{ok=$true;rows=@()}}
        {Get-DuneDockerDeepDesertInstances}|Should -Throw '*no longer matches*'
    }
}
