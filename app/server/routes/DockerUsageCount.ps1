# Keep the Docker preference separate from the Windows host configuration API.
Register-DuneRoute -Method GET -Path '/api/docker/usage-count' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    $config=Read-DuneConfigRaw
    Write-DuneJson -Response $res -Body @{values=@{AnonymousUsageEnabled=[string]$config.AnonymousUsageEnabled}}
}

Register-DuneRoute -Method PUT -Path '/api/docker/usage-count' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    if($body -isnot [hashtable] -or $body.Count -ne 1 -or $body.values -isnot [hashtable] -or
        $body.values.Count -ne 1 -or -not $body.values.ContainsKey('AnonymousUsageEnabled') -or
        ($body.values.AnonymousUsageEnabled -isnot [bool] -and $body.values.AnonymousUsageEnabled -isnot [string]) -or
        [string]$body.values.AnonymousUsageEnabled -notmatch '^(?i:true|false)$'){
        Write-DuneError -Response $res -Status 400 -Message 'Supply only an AnonymousUsageEnabled boolean preference.';return
    }
    $value=([string]$body.values.AnonymousUsageEnabled).ToLowerInvariant()
    $saved=Invoke-WithDuneLock -Name 'config' -Script {Save-DuneConfig -Config @{AnonymousUsageEnabled=$value}}
    Write-DuneJson -Response $res -Body @{ok=$true;values=@{AnonymousUsageEnabled=[string]$saved.AnonymousUsageEnabled}}
}
