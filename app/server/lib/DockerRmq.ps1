function Send-DuneDockerRmqCommands {
    param([hashtable[]]$Fields,[int]$SpacingMilliseconds=0,[string]$Action='server-command',[hashtable]$Extra)
    if(-not $Fields.Count){return @{ok=$false;status=400;message='At least one command is required.'}}
    $packets=[Collections.Generic.List[object]]::new()
    $batch=[Collections.Generic.List[hashtable]]::new()
    $limit=[Math]::Max(1,[Math]::Min(128,[Math]::Floor(15000/[Math]::Max(1,$SpacingMilliseconds))))
    foreach($field in $Fields){
        $candidate=@($batch.ToArray())+@($field)
        $bytes=[Text.Encoding]::UTF8.GetByteCount((ConvertTo-Json -InputObject $candidate -Depth 12 -Compress))
        if($batch.Count -and ($bytes -gt 40000 -or $candidate.Count -gt $limit)){$packets.Add([object[]]$batch.ToArray());$batch.Clear()}
        if([Text.Encoding]::UTF8.GetByteCount((ConvertTo-Json -InputObject $field -Depth 12 -Compress)) -gt 40000){return @{ok=$false;status=400;message='A game command exceeds the transport limit.'}}
        $batch.Add($field)
    }
    if($batch.Count){$packets.Add([object[]]$batch.ToArray())}
    $sent=0
    foreach($packet in $packets){
        $reply=Invoke-DuneDockerManager -Request @{action='rmq.publish';fields=[object[]]$packet;authToken=$script:DuneRmqAuthToken;spacingMilliseconds=$SpacingMilliseconds}
        if(-not $reply.ok){return @{ok=$false;status=503;message=$reply.error;enqueued=$sent}}
        $id=$reply.data.operation.id;$deadline=[DateTime]::UtcNow.AddSeconds(45);$finished=$false
        while([DateTime]::UtcNow -lt $deadline){
            Start-Sleep -Milliseconds 250
            $current=Invoke-DuneDockerManager -Request @{action='status'}
            if(-not $current.ok){return @{ok=$false;status=503;message='Game command delivery could not be verified. Check the result before retrying.';enqueued=$sent}}
            $operation=$current.data.operation
            if($operation.id -ne $id -or $operation.phase -in @('failed','interrupted')){return @{ok=$false;status=502;message=$(if($operation.error){$operation.error}else{'Game command delivery changed. Check before retrying.'});enqueued=$sent}}
            if($operation.phase -eq 'completed'){$sent+=[int]$operation.result.enqueued;$finished=$true;break}
        }
        if(-not $finished){return @{ok=$false;status=504;message='The game command is still pending. Check before retrying.';enqueued=$sent}}
    }
    $result=@{ok=$true;action=$Action;message='Game command queued.';total=$sent;raw="{ok,enqueued,$sent}"}
    if($Extra){foreach($key in $Extra.Keys){$result[$key]=$Extra[$key]}}
    return $result
}
