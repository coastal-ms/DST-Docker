BeforeAll {
    . (Join-Path $PSScriptRoot '_TestHelpers.ps1')
    Import-DstLib 'DockerConsole.ps1'
}
Describe 'Persistent Docker console port' {
    It 'defaults a new installation to8088 without creating settings' {
        $path=Join-Path $TestDrive 'new/console.json'
        Get-DuneDockerConsolePort -Path $path|Should -Be 8088
        Test-Path $path|Should -BeFalse
    }
    It 'persists a chosen port through independent reads and subsequent changes' {
        $path=Join-Path $TestDrive 'saved/console.json'
        Set-DuneDockerConsolePort -Path $path -Port 9090
        Get-DuneDockerConsolePort -Path $path|Should -Be 9090
        Set-DuneDockerConsolePort -Path $path -Port 8088
        Get-DuneDockerConsolePort -Path $path|Should -Be 8088
        @(Get-ChildItem (Split-Path $path) -Force).Count|Should -Be 1
    }
    It 'refuses corrupt or untyped saved values instead of choosing a surprise port' {
        $path=Join-Path $TestDrive 'bad.json'
        foreach($raw in @('{','{"port":true}','{"port":"9090"}','{"port":80}','{"port":65536}','{"port":8088.5}')){
            [IO.File]::WriteAllText($path,$raw)
            {Get-DuneDockerConsolePort -Path $path}|Should -Throw
            [IO.File]::ReadAllText($path)|Should -BeExactly $raw
        }
    }
}

Describe 'Private Docker console listener' {
    BeforeEach {
        $script:OldPrivatePort=$env:DST_HTTP_INTERNAL_PORT
        $script:OldTlsConfig=$env:DST_TLS_PROXY_CONFIG
    }
    AfterEach {
        $env:DST_HTTP_INTERNAL_PORT=$script:OldPrivatePort
        $env:DST_TLS_PROXY_CONFIG=$script:OldTlsConfig
    }
    It 'uses the private port only with a configured TLS proxy' {
        $env:DST_TLS_PROXY_CONFIG='fixture-proxy.json'
        $env:DST_HTTP_INTERNAL_PORT='18088'
        Get-DuneDockerListenerPort|Should -Be 18088
        $env:DST_TLS_PROXY_CONFIG=''
        {Get-DuneDockerListenerPort}|Should -Throw
    }
    It 'rejects malformed private ports' {
        $env:DST_TLS_PROXY_CONFIG='fixture-proxy.json'
        foreach($value in @('true','80','65536','18088.5')){
            $env:DST_HTTP_INTERNAL_PORT=$value
            {Get-DuneDockerListenerPort}|Should -Throw
        }
    }
}
