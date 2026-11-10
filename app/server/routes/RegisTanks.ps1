Register-DuneRoute -Method GET -Path '/api/gameplay/vehicles/regis-tanks' -Handler {
    param($req, $res, $routeParams, $body)
    $ctx = Get-DuneGameConfigContext
    if (-not $ctx.ok) { Write-DuneError -Response $res -Status $ctx.status -Message $ctx.message; return }
    try { Write-DuneJson -Response $res -Body (Get-DuneRegisTankSupport -Ip $ctx.ip) }
    catch { Write-DuneError -Response $res -Status 503 -Message $_.Exception.Message }
}

Register-DuneRoute -Method GET -Path '/api/gameconfig/regis-tanks' -Handler {
    param($req, $res, $routeParams, $body)
    if ($env:DST_HOSTING_BACKEND -eq 'docker') {
        $reply = Invoke-DuneDockerManager -Request @{action='regis.status'}
        if (-not $reply.ok) { Write-DuneError -Response $res -Status 503 -Message $reply.error; return }
        Write-DuneJson -Response $res -Body $reply.data; return
    }
    $ctx = Get-DuneGameConfigContext
    if (-not $ctx.ok) { Write-DuneError -Response $res -Status $ctx.status -Message $ctx.message; return }
    try {
        $deployment = Get-DuneRegisTankDeployment -Ip $ctx.ip
        Write-DuneJson -Response $res -Body @{enabled=($deployment.managed -and $deployment.optedIn);supported=$deployment.supported;legacyPending=($deployment.managed -and -not $deployment.optedIn)}
    } catch { Write-DuneError -Response $res -Status 503 -Message $_.Exception.Message }
}

Register-DuneRoute -Method PUT -Path '/api/gameconfig/regis-tanks' -Handler {
    param($req, $res, $routeParams, $body)
    if ($body -isnot [hashtable] -or $body.enabled -isnot [bool]) { Write-DuneError -Response $res -Status 400 -Message 'enabled must be a boolean.'; return }
    if ($env:DST_HOSTING_BACKEND -eq 'docker') {
        if ($body.ContainsKey('acknowledgeStoredTanks') -and $body.acknowledgeStoredTanks -isnot [bool]) { Write-DuneError -Response $res -Status 400 -Message 'acknowledgeStoredTanks must be a boolean.'; return }
        $reply = Invoke-DuneDockerManager -Request @{action='regis.set';enabled=$body.enabled;acknowledgeStoredTanks=($body.acknowledgeStoredTanks -eq $true)}
        if (-not $reply.ok) { Write-DuneError -Response $res -Status 409 -Message $reply.error; return }
        Write-DuneJson -Response $res -Body @{operationId=$reply.data.operation.id}; return
    }
    $ctx = Get-DuneGameConfigContext
    if (-not $ctx.ok) { Write-DuneError -Response $res -Status $ctx.status -Message $ctx.message; return }
    try {
        $ack = $body.acknowledgeStoredTanks -is [bool] -and $body.acknowledgeStoredTanks
        $result = Invoke-WithDuneLock -Name 'regis-tanks-activation' -Script { Set-DuneRegisTankCompatibility -Ip $ctx.ip -Enabled $body.enabled -AcknowledgeStoredTanks:$ack }
        Write-DuneJson -Response $res -Body $result
    } catch { Write-DuneError -Response $res -Status 400 -Message $_.Exception.Message }
}

Register-DuneRoute -Method POST -Path '/api/gameconfig/regis-tanks/recover' -Handler {
    param($req, $res, $routeParams, $body)
    if ($env:DST_HOSTING_BACKEND -ne 'docker') { Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.'; return }
    $reply = Invoke-DuneDockerManager -Request @{action='regis.recover'}
    if (-not $reply.ok) { Write-DuneError -Response $res -Status 409 -Message $reply.error; return }
    Write-DuneJson -Response $res -Body @{operationId=$reply.data.operation.id}
}

Register-DuneRoute -Method POST -Path '/api/gameplay/vehicles/regis-tanks' -Handler {
    param($req, $res, $routeParams, $body)
    try {
        $actorId = [long](Get-DuneBodyValue -Body $body -Name 'actor_id')
        $template = [string](Get-DuneBodyValue -Body $body -Name 'template_name')
        Invoke-DunePlayerWriteRoute -Response $res -Action { param($ip) Invoke-DuneRegisTankGrant -Ip $ip -ActorId $actorId -TemplateName $template }
    } catch { Write-DuneError -Response $res -Status 400 -Message $_.Exception.Message }
}
