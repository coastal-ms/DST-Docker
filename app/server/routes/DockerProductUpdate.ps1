Register-DuneRoute -Method GET -Path '/api/docker/product-update' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    $reply=Invoke-DuneDockerManager -ProductUpdater -Request @{action='status';force=([string]$req.QueryString['force'] -eq '1')}
    if(-not $reply.ok){Write-DuneError -Response $res -Status 409 -Message $reply.error;return}
    $reply.data.currentVersion=[string]$script:DuneToolVersion
    Write-DuneJson -Response $res -Body $reply.data
}

Register-DuneRoute -Method POST -Path '/api/docker/product-update' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    if($body -isnot [hashtable] -or $body.Count -ne 3 -or [string]$body.tag -cnotmatch '^v\d+\.\d+\.\d+$' -or
        [string]$body.commit -cnotmatch '^[a-f0-9]{40}$' -or $body.confirmation -cne 'UPDATE DST DOCKER'){
        Write-DuneError -Response $res -Status 400 -Message 'Confirm the selected DST Docker release.';return
    }
    $reply=Invoke-DuneDockerManager -ProductUpdater -Request @{action='install';tag=$body.tag;commit=$body.commit;confirmation=$body.confirmation}
    if(-not $reply.ok){Write-DuneError -Response $res -Status 409 -Message $reply.error;return}
    Write-DuneJson -Response $res -Body @{supported=$true;operation=$reply.data}
}
