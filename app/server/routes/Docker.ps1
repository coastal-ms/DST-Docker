foreach ($fileBrowserMethod in @('GET','HEAD','POST','PUT','PATCH','DELETE')) {
    Register-DuneRoute -Method $fileBrowserMethod -Path '/api/docker/file-browser/{path*}' -StreamBody -Handler {
        param($req,$res,$routeParams,$body)
        Invoke-DuneDockerFileBrowser -Request $req -Response $res
    }
}

Register-DuneRoute -Method POST -Path '/api/docker/client-files/transform' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    if($body -isnot [hashtable]){Write-DuneError -Response $res -Status 400 -Message 'Supply the selected client files.';return}
    try{Write-DuneJson -Response $res -Body (Convert-DuneBrowserClientSettings -Request $body)}
    catch{Write-DuneError -Response $res -Status 400 -Message $_.Exception.Message}
}

Register-DuneRoute -Method GET -Path '/api/docker/memory-balancing' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    $reply=Invoke-DuneDockerManager -Request @{action='memory.policy'}
    if(-not $reply.ok){Write-DuneError -Response $res -Status 503 -Message $reply.error;return}
    Write-DuneJson -Response $res -Body $reply.data
}

Register-DuneRoute -Method PUT -Path '/api/docker/memory-balancing' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    if($body -isnot [hashtable] -or $body.enabled -isnot [bool]){Write-DuneError -Response $res -Status 400 -Message 'Supply a JSON boolean for memory balancing.';return}
    $reply=Invoke-DuneDockerManager -Request @{action='memory.policy.set';enabled=$body.enabled}
    if(-not $reply.ok){Write-DuneError -Response $res -Status 409 -Message $reply.error;return}
    Write-DuneJson -Response $res -Body $reply.data
}

Register-DuneRoute -Method GET -Path '/api/docker/log-exports/{id}' -LocalOnly -Handler {
    param($req,$res,$routeParams,$body)
    $id=[string]$routeParams.id
    if($env:DST_HOSTING_BACKEND -ne 'docker' -or $id -cnotmatch '^[a-f0-9]{32}$'){
        Write-DuneError -Response $res -Status 404 -Message 'Log export not found.';return
    }
    $path=Join-Path '/control/log-exports' ($id+'.zip')
    $file=Get-Item -LiteralPath $path -ErrorAction SilentlyContinue
    if(-not $file -or $file.PSIsContainer -or $file.LinkType){Write-DuneError -Response $res -Status 404 -Message 'This log export is unavailable or expired. Export it again.';return}
    $res.Headers['Content-Disposition']='attachment; filename="DST-logs.zip"'
    $res.Headers['X-Content-Type-Options']='nosniff'
    Write-DuneFile -Response $res -Path $path
}

Register-DuneRoute -Method GET -Path '/api/docker/resources' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    $reply=Invoke-DuneDockerManager -Request @{action='resources.get'}
    if(-not $reply.ok){Write-DuneError -Response $res -Status 503 -Message $reply.error;return}
    Write-DuneJson -Response $res -Body $reply.data
}

Register-DuneRoute -Method PUT -Path '/api/docker/resources' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    if($body -isnot [hashtable]){Write-DuneError -Response $res -Status 400 -Message 'Supply the server resource allocations.';return}
    $reply=Invoke-DuneDockerManager -Request @{action='resources.set';memoryGiB=$body.memoryGiB;cpuCount=$body.cpuCount;maps=$body.maps}
    if(-not $reply.ok){Write-DuneError -Response $res -Status 409 -Message $reply.error;return}
    Write-DuneJson -Response $res -Body $reply.data
}

Register-DuneRoute -Method GET -Path '/api/docker/setup' -Handler {
    param($req, $res, $routeParams, $body)
    if ($env:DST_HOSTING_BACKEND -ne 'docker') { Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.'; return }
    $result = Invoke-DuneDockerManager -Request @{action='status'}
    Write-DuneJson -Response $res -Body $result
}

Register-DuneRoute -Method POST -Path '/api/docker/setup' -Handler {
    param($req, $res, $routeParams, $body)
    if ($env:DST_HOSTING_BACKEND -ne 'docker') { Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.'; return }
    $action = [string]$body.action
    if ($action -notin @('database.create','database.initialize','database.migrate','world.configure','credentials.save','connections.prepare','services.prepare','services.start','services.stop','games.refresh-adapters','backups.create','backups.verify','backups.restore')) {
        Write-DuneError -Response $res -Status 400 -Message 'Unsupported setup action.'; return
    }
    $request = @{action=$action}
    if ($action -in @('services.stop','backups.restore','games.refresh-adapters')) {
        $description = if($action -eq 'backups.restore'){'restoring the battlegroup database'}else{'stopping the battlegroup'}
        if (-not (Test-DuneDisruptiveActionGuard -Req $req -Res $res -Action $description)) { return }
    }
    if ($action -eq 'database.create') {
        $port=0
        if (-not [int]::TryParse([string]$body.port,[ref]$port)) { Write-DuneError -Response $res -Status 400 -Message 'Choose a database port.'; return }
        $request.port=$port
    }
    if ($action -eq 'credentials.save') { $request.token=[string]$body.token }
    if ($action -eq 'world.configure') { $request.profile=$body.profile }
    if ($action -in @('backups.verify','backups.restore')) { $request.backupId=[string]$body.backupId }
    if ($action -eq 'backups.restore') { $request.confirmation=[string]$body.confirmation }
    $result = Invoke-DuneDockerManager -Request $request
    Write-DuneJson -Response $res -Body $result
}
Register-DuneRoute -Method POST -Path '/api/docker/owner/setup' -Handler {
    param($req,$res,$routeParams,$body)
    try{
        if($body -isnot [hashtable] -or $body.username -isnot [string] -or $body.password -isnot [string]){throw 'Enter an owner username and password.'}
        $result=New-DuneDockerOwner -Username $body.username -Password $body.password -Request $req
        Set-DunePortalSessionCookie -Response $res -Token $result.token -Request $req
        Write-DuneJson -Response $res -Body @{accountLoginEnabled=$true;authenticated=$true;mustChangePassword=$false;ownerSetupRequired=$false;
            account=(Get-DunePortalPublicAccount $result.account)}
    }catch{Write-DuneError -Response $res -Status 400 -Message $_.Exception.Message}
}
