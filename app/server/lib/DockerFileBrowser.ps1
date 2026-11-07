# The helper is noauth on loopback only. Every request goes through the console's
# owner/session/origin checks; no console credentials are sent to the helper.
function Invoke-DuneDockerFileBrowser {
    param($Request, $Response)
    if ($env:DST_HOSTING_BACKEND -ne 'docker') {
        Write-DuneError -Response $Response -Status 404 -Message 'Docker hosting is not enabled.'; return
    }
    $prefix = '/api/docker/file-browser/'
    $path = [string]$Request.Url.AbsolutePath
    if (-not $path.StartsWith($prefix, [StringComparison]::Ordinal)) {
        Write-DuneError -Response $Response -Status 404 -Message 'File Browser path not found.'; return
    }
    $method = [string]$Request.HttpMethod
    $action = if ($method -in @('GET','HEAD')) { 'files.endpoint' } else { 'files.write-access' }
    $reply = Invoke-DuneDockerManager -Request @{action=$action}
    if ($reply.ok -and -not $reply.data.available -and $method -eq 'GET' -and $path -eq $prefix) {
        $reply = Invoke-DuneDockerManager -Request @{action='files.open'}
    }
    $port = 0
    if (-not $reply.ok -or -not $reply.data.available -or
        -not [int]::TryParse([string]$reply.data.port, [ref]$port) -or $port -lt 1024 -or $port -gt 65535) {
        Write-DuneError -Response $Response -Status 503 -Message 'File Browser is unavailable. Finish any pending server operation, then reopen it from the dashboard.'; return
    }
    # Build a fixed authority, never resolve a user-supplied absolute URI.
    $target = [Uri]::new(('http://127.0.0.1:{0}{1}{2}' -f $port, $path, $Request.Url.Query))
    if (-not $target.AbsolutePath.StartsWith($prefix, [StringComparison]::Ordinal)) {
        Write-DuneError -Response $Response -Status 400 -Message 'Invalid File Browser path.'; return
    }
    $handler = [Net.Http.SocketsHttpHandler]::new()
    $handler.AllowAutoRedirect = $false
    $handler.UseCookies = $false
    $handler.UseProxy = $false
    $handler.ConnectTimeout = [TimeSpan]::FromSeconds(5)
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = [Threading.Timeout]::InfiniteTimeSpan
    $message = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::new($method), $target)
    $upstream = $null
    try {
        # The embedded UI sets its own JWT cookie for window.open downloads.
        # Forward only that cookie, never the console session or launch token.
        $fileCookie = $Request.Cookies['auth']
        if ($fileCookie -and $fileCookie.Value.Length -le 16384 -and
            $fileCookie.Value -cmatch '^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$') {
            [void]$message.Headers.TryAddWithoutValidation('Cookie', 'auth=' + $fileCookie.Value)
        }
        if ($Request.HasEntityBody) {
            $message.Content = [Net.Http.StreamContent]::new($Request.InputStream)
            if ($Request.ContentLength64 -ge 0) { $message.Content.Headers.ContentLength = $Request.ContentLength64 }
            if ($Request.ContentType) { [void]$message.Content.Headers.TryAddWithoutValidation('Content-Type', [string]$Request.ContentType) }
        }
        foreach ($name in @('X-Auth','X-Encoding','Range','If-Range','If-Match','If-None-Match','If-Modified-Since','If-Unmodified-Since',
                            'Tus-Resumable','Upload-Length','Upload-Offset','Upload-Metadata','Upload-Defer-Length')) {
            if ($Request.Headers[$name]) { [void]$message.Headers.TryAddWithoutValidation($name, [string]$Request.Headers[$name]) }
        }
        $upstream = $client.SendAsync($message, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        $Response.StatusCode = [int]$upstream.StatusCode
        $Response.Headers['X-Content-Type-Options'] = 'nosniff'
        $Response.Headers['Cache-Control'] = 'no-store'
        foreach ($name in @('ETag','Last-Modified','Accept-Ranges','Content-Range','Content-Disposition','Content-Security-Policy','X-Renew-Token',
                            'Tus-Resumable','Tus-Version','Tus-Extension','Tus-Max-Size','Upload-Offset','Upload-Length','Upload-Expires')) {
            $values = $null
            if ($upstream.Headers.TryGetValues($name, [ref]$values) -or $upstream.Content.Headers.TryGetValues($name, [ref]$values)) {
                $Response.Headers[$name] = [string]::Join(', ', $values)
            }
        }
        if ($upstream.Headers.Location) {
            $location = [string]$upstream.Headers.Location.OriginalString
            # Only the helper's own base path may redirect through the console.
            if (-not $location.StartsWith($prefix, [StringComparison]::Ordinal)) {
                Write-DuneError -Response $Response -Status 502 -Message 'File Browser returned an unexpected redirect.'; return
            }
            $Response.Headers['Location'] = $location
        }
        if ($upstream.Content.Headers.ContentType) { $Response.ContentType = [string]$upstream.Content.Headers.ContentType }
        if ($null -ne $upstream.Content.Headers.ContentLength) {
            $Response.ContentLength64 = [long]$upstream.Content.Headers.ContentLength
        } elseif ($method -ne 'HEAD' -and $Response.StatusCode -notin @(204,304)) { $Response.SendChunked = $true }
        if ($method -ne 'HEAD' -and $Response.StatusCode -notin @(204,304)) {
            $stream = $upstream.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
            $stream.CopyToAsync($Response.OutputStream).GetAwaiter().GetResult()
        }
    } catch {
        # No upstream URI, query (which can carry a download JWT), or credential
        # belongs in the error response or routine log.
        try { Write-DuneError -Response $Response -Status 502 -Message 'File Browser connection ended. Reopen it from the dashboard and try again.' } catch {}
    } finally {
        if ($upstream) { $upstream.Dispose() }
        $message.Dispose()
        $client.Dispose()
    }
}
