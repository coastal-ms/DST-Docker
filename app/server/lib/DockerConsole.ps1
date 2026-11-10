# Persistent Docker console configuration; game ports are separate.
function Get-DuneDockerConsolePort {
    param([string]$Path='/data/config/DuneServer/docker-console.json')
    if(-not (Test-Path -LiteralPath $Path)){return 8088}
    try{$value=Get-Content -LiteralPath $Path -Raw|ConvertFrom-Json -AsHashtable}catch{throw 'The saved Docker console port could not be read.'}
    if($value.port -isnot [long] -and $value.port -isnot [int]){throw 'The saved Docker console port must be a number.'}
    if($value.port -lt 1024 -or $value.port -gt 65535){throw 'Choose a Docker console port between 1024 and 65535.'}
    return [int]$value.port
}

function Get-DuneDockerListenerPort {
    if(-not $env:DST_HTTP_INTERNAL_PORT){return Get-DuneDockerConsolePort}
    $port=0
    if(-not $env:DST_TLS_PROXY_CONFIG -or -not [int]::TryParse($env:DST_HTTP_INTERNAL_PORT,[ref]$port) -or $port -lt 1024 -or $port -gt 65535){
        throw 'The private HTTPS console listener configuration is invalid.'
    }
    return $port
}

function Set-DuneDockerConsolePort {
    param([Parameter(Mandatory)][ValidateRange(1024,65535)][int]$Port,
          [string]$Path='/data/config/DuneServer/docker-console.json')
    $directory=Split-Path -Parent $Path
    [void][IO.Directory]::CreateDirectory($directory)
    $temporary=Join-Path $directory ('.console-'+[guid]::NewGuid().ToString('N')+'.tmp')
    try{
        [IO.File]::WriteAllText($temporary,(@{port=$Port}|ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
        if($IsLinux){[IO.File]::SetUnixFileMode($temporary,[IO.UnixFileMode]::UserRead -bor [IO.UnixFileMode]::UserWrite)}
        [IO.File]::Move($temporary,$Path,$true)
    }finally{if(Test-Path -LiteralPath $temporary){[IO.File]::Delete($temporary)}}
}
