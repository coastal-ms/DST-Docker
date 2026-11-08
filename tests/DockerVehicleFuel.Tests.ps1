BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'Gameplay.ps1'
    Import-DstLib 'DockerPlayerCoordinates.ps1'
    Import-DstLib 'DockerVehicleFuel.ps1'
    function Invoke-DuneSqlQuery {param($Ip,$Sql,$ReadOnly,$MaxRows,$TimeoutSec)}
    function Invoke-DuneDockerManager {param($Request)}
    function Get-DuneDockerHostScope {}
}
Describe 'Native saved vehicle fuel' {
    BeforeEach {
        Mock Get-DuneDockerHostScope { @{world=('a'*32)} }
        Mock Invoke-DuneSqlQuery {
            if($ReadOnly){@{ok=$true;columns=@('class','partition_id');rows=@(,@('/Game/Test.BP_Buggy_CHOAM_C','1'))}}
            else{@{ok=$true}}
        }
        Mock Invoke-DuneDockerManager { @{ok=$true;data=@{projectId=('a'*32);services=@(@{component='game-1';state='exited'},@{component='game-8';state='running'})}} }
    }
    It 'writes only a verified saved fuel field with full property readback in one transaction' {
        $result=Invoke-DuneDockerVehicleRefuel -Ip docker -VehicleId 17
        $result.ok|Should -BeTrue
        $result.message|Should -Match 'map starts again'
        Should -Invoke Invoke-DuneSqlQuery -Times 1 -Exactly -ParameterFilter {
            -not $ReadOnly -and $Sql -match 'JOIN dune.vehicles' -and $Sql -match 'FOR UPDATE OF a FOR SHARE OF v' -and
            $Sql -match "IS DISTINCT FROM 'number'" -and $Sql -match 'touched<>1' -and $Sql -match 'IS DISTINCT FROM expected'
        }
    }
    It 'refuses an active or unobservable target map before writing fuel' {
        foreach($state in @('running','restarting','unknown')){
            Mock Invoke-DuneDockerManager { @{ok=$true;data=@{projectId=('a'*32);services=@(@{component='game-1';state=$state})}} }
            (Invoke-DuneDockerVehicleRefuel -Ip docker -VehicleId 17).ok|Should -BeFalse
        }
        Should -Invoke Invoke-DuneSqlQuery -Times 0 -Exactly -ParameterFilter {-not $ReadOnly}
    }
    It 'refuses a missing target map or another project' {
        Mock Invoke-DuneDockerManager { @{ok=$true;data=@{projectId=('a'*32);services=@(@{component='game-8';state='exited'})}} }
        (Invoke-DuneDockerVehicleRefuel -VehicleId 17).ok|Should -BeFalse
        Mock Invoke-DuneDockerManager { @{ok=$true;data=@{projectId=('b'*32);services=@(@{component='game-1';state='exited'})}} }
        (Invoke-DuneDockerVehicleRefuel -VehicleId 17).ok|Should -BeFalse
        Should -Invoke Invoke-DuneSqlQuery -Times 0 -Exactly -ParameterFilter {-not $ReadOnly}
    }
    It 'requires all maps stopped for a vehicle without a saved partition' {
        Mock Invoke-DuneSqlQuery { @{ok=$true;columns=@('class','partition_id');rows=@(,@('BP_Buggy_CHOAM_C',$null))} } -ParameterFilter {$ReadOnly}
        (Invoke-DuneDockerVehicleRefuel -VehicleId 17).ok|Should -BeFalse
        Should -Invoke Invoke-DuneSqlQuery -Times 0 -Exactly -ParameterFilter {-not $ReadOnly}
    }
    It 'rejects a missing vehicle and reports transaction failure honestly' {
        (Invoke-DuneDockerVehicleRefuel -VehicleId 0).ok|Should -BeFalse
        Mock Invoke-DuneSqlQuery { @{ok=$true;columns=@('class','partition_id');rows=@()} } -ParameterFilter {$ReadOnly}
        (Invoke-DuneDockerVehicleRefuel -VehicleId 17).ok|Should -BeFalse
        Mock Invoke-DuneSqlQuery { @{ok=$true;columns=@('class','partition_id');rows=@(,@('BP_Buggy_CHOAM_C','1'))} } -ParameterFilter {$ReadOnly}
        Mock Invoke-DuneSqlQuery { @{ok=$false;error='fixture rollback'} } -ParameterFilter {-not $ReadOnly}
        $result=Invoke-DuneDockerVehicleRefuel -VehicleId 17
        $result.ok|Should -BeFalse
        $result.error|Should -Match 'fixture rollback'
    }
}
