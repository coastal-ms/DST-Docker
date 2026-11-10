BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerManager.ps1'
    Import-DstLib 'Pods.ps1'
    Import-DstLib 'Status.ps1'
}
Describe 'Existing service inspector on Docker' {
    BeforeEach {
        $script:previousBackend=$env:DST_HOSTING_BACKEND
        $env:DST_HOSTING_BACKEND='docker'
        $script:metadata=@{desiredState='stopped';database=@{name='fixture';state='exited';health='healthy'};
          services=@(@{component='game-1';state='created';desiredState='stopped';gameReady=$false},@{component='director';state='exited';desiredState='stopped'});
          connectionServices=@(@{component='rmq-game';state='exited';health='unhealthy'});plan=@{games=@(@{partition=1;map='Survival_1'})}}
        Mock Invoke-DuneDockerManager { @{ok=$true;data=$script:metadata} }
    }
    AfterEach {$env:DST_HOSTING_BACKEND=$script:previousBackend}
    It 'projects this world into the existing inspector without treating cached health as readiness' {
        $result=Get-DunePodsList
        $result.ok|Should -BeTrue
        $result.count|Should -Be 4
        $database=$result.pods|Where-Object component -eq 'postgres'
        $database.phase|Should -Be 'Stopped'
        $database.ready|Should -Be '0/1'
        $database.restarts|Should -BeNullOrEmpty
        ($result.pods|Where-Object component -eq 'game-1').map|Should -Be 'Survival_1'
    }
    It 'requires a game heartbeat and broker health before showing ready containers' {
        $script:metadata.services[0].state='running'
        $script:metadata.connectionServices[0].state='running'
        $result=Get-DunePodsList
        ($result.pods|Where-Object component -eq 'game-1').ready|Should -Be '0/1'
        ($result.pods|Where-Object component -eq 'rmq-game').ready|Should -Be '0/1'
        $script:metadata.services[0].gameReady=$true
        $script:metadata.connectionServices[0].health='healthy'
        (Get-DunePodsList).pods|Where-Object component -in @('game-1','rmq-game')|ForEach-Object {$_.ready|Should -Be '1/1'}
    }
    It 'shows current details only for a container in the selected world' {
        $result=Get-DunePodEvents -Namespace docker -Name fixture
        $result.ok|Should -BeTrue
        $result.events.Count|Should -Be 0
        ($result.describe|ConvertFrom-Json).name|Should -Be 'fixture'
        (Get-DunePodEvents -Namespace foreign -Name postgres).status|Should -Be 404
        (Get-DunePodEvents -Namespace docker -Name foreign).status|Should -Be 404
    }
    It 'keeps unavailable manager observations an error instead of a successful empty list' {
        Mock Invoke-DuneDockerManager {@{ok=$false;error='offline'}}
        (Get-DunePodsList).status|Should -Be 503
    }
    It 'routes shared host and battlegroup status consumers to Docker instead of Hyper-V or SSH' {
        Mock Get-DuneDockerStatus {@{vm=@{kind='docker';running=$true};bg=@{available=$true;state='stopped';title='Fixture';gameServers=@()}}}
        (Get-DuneVmStatus).kind|Should -Be 'docker'
        (Get-DuneBattlegroupSnapshot).state|Should -Be 'stopped'
        Should -Invoke Get-DuneDockerStatus -Times 2 -Exactly -ParameterFilter {$LifecycleOnly}
    }
}
