$ErrorActionPreference='Stop'
$env:DST_HOSTING_BACKEND='docker'
. /opt/dst/app/server/lib/DockerRmq.ps1
. /opt/dst/app/server/lib/Rmq.ps1
$script:packets=[Collections.Generic.List[object]]::new()
$script:current=$null
function Invoke-DuneDockerManager {
    param([hashtable]$Request)
    if($Request.action -eq 'rmq.publish'){
        $copy=$Request | ConvertTo-Json -Depth 16 -Compress | ConvertFrom-Json -AsHashtable
        if($copy.fields -isnot [array]){throw 'The wire fields must remain an array for a one-command packet.'}
        $script:packets.Add($copy)
        $script:current=@{id="fixture-$($script:packets.Count)";phase='completed';result=@{enqueued=$copy.fields.Count}}
    }
    return @{ok=$true;data=@{operation=$script:current}}
}
$single=Send-DuneRmqServerCommand -Fields @{ServerCommand='AwardXP';PlayerId='fixture';XP=5}
if(-not $single.ok -or $single.total -ne 1){throw 'Single-command native transport failed.'}
$text=('生命 quoted " ' * 400)
$fields=@(1..9 | ForEach-Object {@{ServerCommand='ServiceBroadcast';BroadcastType='Generic';BroadcastPayload=@{LocalizedText=@(@{Key='en';Title=$text;Body=$text})}}})
$batch=Send-DuneRmqServerCommandBatch -Fields $fields
if(-not $batch.ok -or $batch.total -ne 9){throw 'Chunked native batch did not confirm every command.'}
if($script:packets.Count -le 2){throw 'The large command batch was not bounded into multiple packets.'}
$decoded=@($script:packets | Select-Object -Skip 1 | ForEach-Object {$_.fields})
if($decoded.Count -ne 9 -or $decoded[0].BroadcastPayload.LocalizedText[0].Title -cne $text){throw 'Nested Unicode broadcast text did not survive the native wire shape.'}
@{ok=$true;single=1;batch=$batch.total;packets=$script:packets.Count;unicode=$true} | ConvertTo-Json -Compress
