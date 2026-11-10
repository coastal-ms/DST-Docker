BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'Gameplay.ps1'
    Import-DstLib 'GameplayPlayers.ps1'
    Import-DstLib 'DockerPlayerCoordinates.ps1'
    function Invoke-DuneSqlQuery {param($Ip,$Sql,$ReadOnly,$MaxRows,$TimeoutSec)}
    function Invoke-DuneRmqTeleportToExact {param($FlsId,$X,$Y,$Z)}
}

Describe 'Native coordinate identity reads' {
    It 'accepts one verified active character with precise numeric coordinates' {
        Mock Invoke-DuneSqlQuery { @{ok=$true;columns=@('character_id','account_id','pawn_id','status','fls_id','map','partition_id','dimension','x','y','z');rows=@(,@('1','2','3','Offline','fixture','Survival_1','1','0','101.25','-202.5','303.75'))} }
        $result=Get-DuneDockerPlayerCoordinateContext -Ip docker -PawnId 3
        $result.ok|Should -BeTrue
        $result.player.pawn_id|Should -Be '3'
        $result.player.x|Should -Be 101.25
        $result.player.y|Should -Be -202.5
    }
    It 'fails closed on a status-query failure' {
        Mock Invoke-DuneSqlQuery { @{ok=$false;error='fixture query failure'} }
        (Get-DuneDockerPlayerCoordinateContext -Ip docker -PawnId 11).ok|Should -BeFalse
        Should -Invoke Invoke-DuneSqlQuery -Times 0 -ParameterFilter {-not $ReadOnly}
    }
    It 'rejects ambiguous active characters instead of choosing the first' {
        Mock Invoke-DuneSqlQuery { @{ok=$true;columns=@('pawn_id');rows=@(,@('11'),@('12'))} }
        (Get-DuneDockerPlayerCoordinateContext -Ip docker -AccountId 10).ok|Should -BeFalse
    }
    It 'rejects non-finite target coordinates' {
        Mock Invoke-DuneSqlQuery { @{ok=$true;columns=@('character_id','account_id','pawn_id','status','fls_id','map','partition_id','dimension','x','y','z');rows=@(,@('1','2','3','Offline','fixture','Survival_1','1','0','NaN','2','3'))} }
        (Get-DuneDockerPlayerCoordinateContext -Ip docker -PawnId 3).ok|Should -BeFalse
    }
    It 'rejects blocked or remapped destination partitions' {
        Mock Invoke-DuneSqlQuery { @{ok=$true;columns=@('partition_id','map','dimension','blocked','expected_map');rows=@(,@('8','DeepDesert','0','true','DeepDesert'))} }
        (Get-DuneDockerPlayerDestinationPartition -Ip docker -PartitionId 8 -ExpectedMap DeepDesert).ok|Should -BeFalse
        Mock Invoke-DuneSqlQuery { @{ok=$true;columns=@('partition_id','map','dimension','blocked','expected_map');rows=@(,@('8','WrongMap','0','false','DeepDesert'))} }
        (Get-DuneDockerPlayerDestinationPartition -Ip docker -PartitionId 8 -ExpectedMap DeepDesert).ok|Should -BeFalse
    }
}

Describe 'Native player relocation paths' {
    BeforeEach {
        $script:source=@{character_id='1001';account_id='101';pawn_id='11';status='Offline';fls_id='SOURCE';map='Survival_1';partition_id='1';dimension='0';x=1.0;y=2.0;z=3.0}
        $script:target=@{character_id='1002';account_id='102';pawn_id='22';status='Offline';fls_id='TARGET';map='Survival_1';partition_id='701';dimension='2';x=101.25;y=-202.5;z=303.75}
        Mock Get-DuneDockerPlayerCoordinateContext { if($PawnId -eq 11){@{ok=$true;player=$script:source}}else{@{ok=$true;player=$script:target}} }
        Mock Get-DuneDockerPlayerDestinationPartition { @{ok=$true;partition=@{partition_id='701';map='Survival_1';dimension='2'}} }
        Mock Invoke-DuneDockerOfflinePlayerPlacement { @{ok=$true;path='sql'} }
        Mock Invoke-DuneRmqTeleportToExact { @{ok=$true;message='queued'} }
    }
    It 'uses the target partition and dimension for the offline move' {
        (Invoke-DuneDockerPlayerTeleportToPlayer -Ip docker -SourcePawnId 11 -TargetPawnId 22).path|Should -Be 'sql'
        Should -Invoke Invoke-DuneDockerOfflinePlayerPlacement -Times 1 -Exactly -ParameterFilter {$Player.pawn_id -eq '11' -and $Partition.partition_id -eq '701' -and $Partition.dimension -eq '2' -and $X -eq 101.25 -and $Y -eq -202.5}
        Should -Invoke Invoke-DuneRmqTeleportToExact -Times 0 -Exactly
    }
    It 'rejects an explicit partition that does not match the selected target' {
        (Invoke-DuneDockerPlayerTeleportToPlayer -Ip docker -SourcePawnId 11 -TargetPawnId 22 -PartitionId 1).ok|Should -BeFalse
        Should -Invoke Invoke-DuneDockerOfflinePlayerPlacement -Times 0 -Exactly
        Should -Invoke Invoke-DuneRmqTeleportToExact -Times 0 -Exactly
    }
    It 'does not move an online player across partitions or dimensions' {
        $script:source.status='Online'
        (Invoke-DuneDockerPlayerTeleportToPlayer -Ip docker -SourcePawnId 11 -TargetPawnId 22).ok|Should -BeFalse
        Should -Invoke Invoke-DuneDockerOfflinePlayerPlacement -Times 0 -Exactly
        Should -Invoke Invoke-DuneRmqTeleportToExact -Times 0 -Exactly
    }
    It 'does not treat a logout in progress as a live teleport' {
        $script:source.status='LoggingOut'
        (Invoke-DuneDockerPlayerTeleportToPlayer -Ip docker -SourcePawnId 11 -TargetPawnId 22).ok|Should -BeFalse
        Should -Invoke Invoke-DuneRmqTeleportToExact -Times 0 -Exactly
    }
    It 'queues same-map online movement for only the source account' {
        $script:source.status='Online';$script:source.partition_id='701';$script:source.dimension='2'
        (Invoke-DuneDockerPlayerTeleportToPlayer -Ip docker -SourcePawnId 11 -TargetPawnId 22).path|Should -Be 'rmq'
        Should -Invoke Invoke-DuneRmqTeleportToExact -Times 1 -Exactly -ParameterFilter {$FlsId -eq 'SOURCE' -and $X -eq 101.25 -and $Y -eq -202.5 -and $Z -eq 303.75}
        Should -Invoke Invoke-DuneDockerOfflinePlayerPlacement -Times 0 -Exactly
    }
}
