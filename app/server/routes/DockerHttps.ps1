Register-DuneRoute -Method GET -Path '/api/docker/https' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    $reply=Invoke-DuneDockerManager -ProductUpdater -Request @{action='https.status';port=(Get-DuneDockerConsolePort)}
    if(-not $reply.ok){Write-DuneError -Response $res -Status 409 -Message $reply.error;return}
    Write-DuneJson -Response $res -Body $reply.data
}

Register-DuneRoute -Method POST -Path '/api/docker/https' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    if($body -isnot [hashtable]){Write-DuneError -Response $res -Status 400 -Message 'Choose an HTTPS action.';return}
    $request=@{port=(Get-DuneDockerConsolePort)}
    switch -CaseSensitive ([string]$body.action) {
        'prepare' {
            $address=$null
            if($body.Count -ne 2 -or $body.address -isnot [string] -or -not [Net.IPAddress]::TryParse($body.address,[ref]$address) -or $address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork){Write-DuneError -Response $res -Status 400 -Message 'Choose the host IPv4 address.';return}
            $request.action='https.prepare';$request.address=$address.ToString()
        }
        'enable' {
            if($body.Count -ne 2 -or $body.sha256 -isnot [string] -or $body.sha256 -cnotmatch '^[a-f0-9]{64}$'){Write-DuneError -Response $res -Status 400 -Message 'Confirm the prepared certificate.';return}
            $request.action='https.enable';$request.sha256=$body.sha256
        }
        'disable' {
            if($body.Count -ne 1){Write-DuneError -Response $res -Status 400 -Message 'Choose the HTTPS action.';return}
            $request.action='https.disable'
        }
        default {Write-DuneError -Response $res -Status 400 -Message 'Choose a supported HTTPS action.';return}
    }
    $reply=Invoke-DuneDockerManager -ProductUpdater -Request $request
    if(-not $reply.ok){Write-DuneError -Response $res -Status 409 -Message $reply.error;return}
    Write-DuneJson -Response $res -Body $reply.data
}

Register-DuneRoute -Method GET -Path '/api/docker/https/certificate' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    $reply=Invoke-DuneDockerManager -ProductUpdater -Request @{action='https.certificate';port=(Get-DuneDockerConsolePort)}
    if(-not $reply.ok -or $reply.data.pem -isnot [string] -or $reply.data.pem.Length -gt 16384 -or $reply.data.pem -notmatch '^-----BEGIN CERTIFICATE-----' -or $reply.data.pem -match 'PRIVATE KEY'){
        Write-DuneError -Response $res -Status 409 -Message 'Prepare HTTPS before downloading its public certificate.';return
    }
    $bytes=[Text.Encoding]::ASCII.GetBytes($reply.data.pem)
    $res.StatusCode=200;$res.ContentType='application/x-x509-ca-cert'
    $res.Headers['Content-Disposition']='attachment; filename="dst-docker-root.crt"'
    $res.Headers['Cache-Control']='no-store'
    $res.Headers['X-Content-Type-Options']='nosniff'
    $res.ContentLength64=$bytes.Length
    $res.OutputStream.Write($bytes,0,$bytes.Length);$res.OutputStream.Close()
}
