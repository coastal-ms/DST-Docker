BeforeAll {
    $module=Join-Path (Split-Path $PSScriptRoot -Parent) 'packaging/docker/wsl_loopback.py'
    $source=Get-Content -LiteralPath $module -Raw
    # Exercise the shipped PowerShell function without requiring a Python
    # interpreter in the PowerShell-only Linux test container.
    $route=[regex]::Match($source,'(?ms)^ROUTE_FUNCTION=r"""\r?\n(?<script>.*?)^"""')
    if(-not $route.Success){throw 'Could not load the loopback route implementation.'}
    Invoke-Expression $route.Groups['script'].Value
    function Get-NetRoute {
        param($AddressFamily,$DestinationPrefix,$PolicyStore='ActiveStore')
        @($script:routes | Where-Object {$_.DestinationPrefix -eq $DestinationPrefix -and $_.Store -eq $PolicyStore})
    }
    function Find-NetRoute {param($RemoteIPAddress) @(@{IPAddress='192.168.23.23';InterfaceIndex=7},@{DestinationPrefix='192.168.23.0/24';NextHop='0.0.0.0';InterfaceIndex=7})}
    function Remove-NetRoute {
        [CmdletBinding(SupportsShouldProcess)]param([Parameter(ValueFromPipeline)]$InputObject)
        process {
            $script:writes++
            $remove=$InputObject
            $script:routes=@($script:routes | Where-Object {-not ($_.DestinationPrefix -eq $remove.DestinationPrefix -and $_.NextHop -eq $remove.NextHop -and $_.Store -eq $remove.Store)})
        }
    }
    function New-NetRoute {
        [CmdletBinding()]param($DestinationPrefix,$InterfaceIndex,$NextHop,$RouteMetric,$PolicyStore)
        $script:writes++
        if($script:failTarget -eq $NextHop){throw 'Synthetic route creation failure'}
        foreach($store in $(if($PolicyStore){@($PolicyStore)}else{@('ActiveStore','PersistentStore')})){
            $script:routes+=@{DestinationPrefix=$DestinationPrefix;InterfaceIndex=$InterfaceIndex;NextHop=$NextHop;RouteMetric=$RouteMetric;Store=$store}
        }
    }
}
Describe 'Explicit Docker same-PC loopback route changes' {
    BeforeEach {
        $script:writes=0;$script:failTarget=''
        $script:routes=@(
            @{DestinationPrefix='8.8.4.4/32';InterfaceIndex=7;NextHop='192.168.23.219';RouteMetric=1;Store='ActiveStore'},
            @{DestinationPrefix='8.8.4.4/32';InterfaceIndex=7;NextHop='192.168.23.219';RouteMetric=1;Store='PersistentStore'},
            @{DestinationPrefix='1.1.1.1/32';InterfaceIndex=7;NextHop='192.168.23.219';RouteMetric=1;Store='ActiveStore'}
        )
    }
    It 'leaves a matching current target completely unchanged' {
        Set-DstDockerLoopbackRoute -PublicIp '8.8.4.4' -Target '192.168.23.219' -ExpectedTarget '192.168.23.219'
        $script:writes | Should -Be 0
    }
    It 'refuses a stale current target before changing any route' {
        {Set-DstDockerLoopbackRoute -PublicIp '8.8.4.4' -Target '192.168.23.106' -ExpectedTarget '192.168.23.218'} | Should -Throw '*changed*'
        $script:writes | Should -Be 0
    }
    It 'changes only the selected public-IP host route in both stores' {
        Set-DstDockerLoopbackRoute -PublicIp '8.8.4.4' -Target '192.168.23.106' -ExpectedTarget '192.168.23.219'
        @($script:routes | Where-Object DestinationPrefix -eq '8.8.4.4/32').NextHop | Should -Be @('192.168.23.106','192.168.23.106')
        @($script:routes | Where-Object DestinationPrefix -eq '1.1.1.1/32').NextHop | Should -Be @('192.168.23.219')
    }
    It 'restores the original VM route if the new route cannot be created' {
        $script:failTarget='192.168.23.106'
        {Set-DstDockerLoopbackRoute -PublicIp '8.8.4.4' -Target '192.168.23.106' -ExpectedTarget '192.168.23.219'} | Should -Throw '*Synthetic*'
        @($script:routes | Where-Object DestinationPrefix -eq '8.8.4.4/32').NextHop | Should -Be @('192.168.23.219','192.168.23.219')
    }
    It 'removes only the chosen host route when router loopback is selected' {
        Set-DstDockerLoopbackRoute -PublicIp '8.8.4.4' -Target $null -ExpectedTarget '192.168.23.219'
        @($script:routes | Where-Object DestinationPrefix -eq '8.8.4.4/32').Count | Should -Be 0
        $script:routes[0].DestinationPrefix | Should -Be '1.1.1.1/32'
    }
}
