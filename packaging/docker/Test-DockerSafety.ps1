$ErrorActionPreference='Stop'
. /opt/dst/app/server/lib/DockerSafety.ps1
$script:fixturePath='/tmp/dst-safety-config.json'
@{host='127.0.0.1';port=18932;database='dune';user='dune'} | ConvertTo-Json | Set-Content $script:fixturePath
$script:metadata=@{projectId=('a'*32);database=@{port=18932;instanceId=('b'*64)};backups=@();operation=@{}}
$script:identity=@{database='dune';role='dune';oid='12345'}
$script:started=$false;$script:mode='valid'
function Invoke-DuneSqlQuery {param($Ip,$Sql,$ReadOnly,$MaxRows,$TimeoutSec) return @{ok=$true}}
function ConvertTo-DuneRowMaps {param($Result) return ,@($script:identity)}
function Invoke-DuneDockerManager {
    param($Request)
    if($Request.action -eq 'backups.create'){$script:started=$true}
    if($script:started){
        $script:metadata.operation=@{id=('c'*32);phase='completed'}
        $script:metadata.backups=@(@{id=('d'*32);name='backup-1234-abcdef12.dump';operationId=('c'*32);phase='completed';bytes=2048;sha256=('e'*64)})
        if($script:mode -eq 'old'){$script:metadata.backups[0].operationId='f'*32}
        if($script:mode -eq 'short'){$script:metadata.backups[0].bytes=100}
        if($script:mode -eq 'changed'){$script:metadata.database.instanceId='f'*64}
    }
    return @{ok=$true;data=$script:metadata}
}
try {
    $first=Get-DuneDockerHostScope -ConfigurationPath $script:fixturePath
    $script:identity.oid='12346'
    $second=Get-DuneDockerHostScope -ConfigurationPath $script:fixturePath
    if($first.key -ceq $second.key){throw 'Database replacement did not change the bound scope.'}
    $script:identity.oid='12345'
    $script:identity.database='other'
    $rejected=$false
    try {Get-DuneDockerHostScope -ConfigurationPath $script:fixturePath | Out-Null}catch{$rejected=$true}
    if(-not $rejected){throw 'A different database connection was accepted.'}
    $script:identity.database='dune'
    $script:realScope=(Get-Command Get-DuneDockerHostScope).ScriptBlock
    function Get-DuneDockerHostScope { & $script:realScope -ConfigurationPath $script:fixturePath }
    foreach($mode in @('valid','old','short','changed')){
        $script:mode=$mode;$script:started=$false;$script:metadata.database.instanceId='b'*64
        $result=Invoke-DuneDockerSafetyBackup
        if($mode -eq 'valid'){
            if(-not $result.ok -or $result.bytes -ne 2048 -or $result.database_scope -cne $first.key){throw 'Verified fresh archive proof was rejected.'}
        } elseif($result.ok){throw "Unsafe $mode backup proof was accepted."}
    }
    @{ok=$true;checks=@('Database OID changes scope','Other database rejected','Fresh operation-bound archive accepted','Old archive rejected','Truncated archive proof rejected','Changed database rejected')} | ConvertTo-Json
} finally {Remove-Item -LiteralPath $script:fixturePath -ErrorAction SilentlyContinue}
