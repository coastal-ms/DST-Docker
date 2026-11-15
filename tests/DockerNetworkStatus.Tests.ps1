BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerManager.ps1'
    Import-DstLib 'PublicIp.ps1'
    function global:Get-DunePortStatus {param($Force,$BattlegroupState,$RequiredPorts,$PublicIp)}
}
Describe 'Docker network settings status propagation' {
    It 'recognizes an existing WSL installation without the newer platform environment variable' {
        $original=$env:DST_HOST_PLATFORM
        try {
            $env:DST_HOST_PLATFORM=$null
            Mock Test-Path {$true} -ParameterFilter {$LiteralPath -eq '/host-control/network-info.json'}
            Mock Get-Content {'{"dockerIp":"192.168.23.106","wslIp":"192.168.23.106","networkingMode":"bridged","routerForwardIp":"192.168.23.106"}'} -ParameterFilter {$LiteralPath -eq '/host-control/network-info.json'}
            Test-DuneDockerWslHost | Should -BeTrue
            $addresses=Get-DuneDockerNetworkAddresses
            $addresses.networkingMode | Should -Be 'bridged'
            $addresses.wslIp | Should -Be '192.168.23.106'
        } finally {$env:DST_HOST_PLATFORM=$original}
    }
    It 'keeps the local Docker address separate while public addresses and player ports change' {
        $snapshot=Join-Path $TestDrive 'status.json'
        @{available=$true;observedAt=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()}|ConvertTo-Json|Set-Content -LiteralPath $snapshot
        $script:networkMetadata=@{profile=@{name='Fixture';address='192.168.1.5';gamePortBase=28777};desiredState='stopped';operation=@{phase='completed'};
            database=@{state='exited';health='healthy'};connectionServices=@();services=@();plan=@{games=@();ports=@{'rmq-game'=29779}}}
        Mock Invoke-DuneDockerManager {@{ok=$true;data=$script:networkMetadata}}
        Mock Get-DuneDockerNetworkAddresses {@{dockerIp='192.168.1.5'}}
        Mock Get-DunePortStatus {param($RequiredPorts) @{cached=$true;results=$RequiredPorts}}
        (Get-DuneDockerStatus -SnapshotPath $snapshot).vm.ip | Should -Be '192.168.1.5'
        $script:networkMetadata.profile.address='8.8.4.4';$script:networkMetadata.profile.gamePortBase=7777
        $script:networkMetadata.plan.ports.'rmq-game'=31982
        $current=Get-DuneDockerStatus -SnapshotPath $snapshot
        $current.vm.ip | Should -Be '192.168.1.5'
        Should -Invoke Get-DunePortStatus -ParameterFilter {$PublicIp -eq '8.8.4.4'} -Times 1 -Exactly
        @($current.ports.results|Where-Object Protocol -eq TCP)[0].Port | Should -Be 31982
        @($current.ports.results|Where-Object Protocol -eq UDP).Port | Should -Be @(7777,7810)
        $script:networkMetadata.profile.address='192.168.1.8'
        (Get-DuneDockerStatus -SnapshotPath $snapshot).vm.ip | Should -Be '192.168.1.5'
    }
}
