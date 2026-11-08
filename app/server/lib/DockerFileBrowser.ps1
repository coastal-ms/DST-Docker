# The helper is noauth on loopback only. Every request goes through the console's
# owner/session/origin checks; no console credentials are sent to the helper.
function Invoke-DuneDockerFileBrowser {
    param($Request, $Response)
    Invoke-DuneDockerWebInterface -Request $Request -Response $Response -Service 'file-browser'
}

function Invoke-DuneDockerDirector {
    param($Request, $Response)
    Invoke-DuneDockerWebInterface -Request $Request -Response $Response -Service 'director'
}

function ConvertTo-DuneDockerDirectorHtml {
    param([string]$Html,[ValidateRange(1024,65535)][int]$Port)
    $bootstrap=@'
<base href="/api/docker/director/">
<script>
(()=>{const prefix='/api/docker/director/',upstream='__DST_UPSTREAM__';
const scoped=input=>{try{const u=new URL(String(input),location.href);if((u.origin===location.origin||u.origin===upstream||(u.protocol==='http:'&&u.host===location.host))&&!u.pathname.startsWith(prefix))return prefix.slice(0,-1)+u.pathname+u.search+u.hash;}catch{}return input;};
const originalFetch=window.fetch.bind(window);
window.fetch=(input,options)=>originalFetch(input instanceof Request?new Request(scoped(input.url),input):scoped(input),options);
const originalOpen=XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open=function(method,url,...args){return originalOpen.call(this,method,scoped(url),...args);};
document.addEventListener('click',event=>{const a=event.target.closest?.('a[href]');if(a)a.href=scoped(a.href);},true);
document.addEventListener('submit',event=>{event.target.action=scoped(event.target.action);},true);
})();
</script>
'@
    $bootstrap=$bootstrap.Replace('__DST_UPSTREAM__',"http://127.0.0.1:$Port")
    $result=[regex]::Replace($Html,'(?i)(src|href|action)=([''"])/(?!/)','$1=$2/api/docker/director/')
    return [regex]::Replace($result,'(?i)<head\b[^>]*>',[Text.RegularExpressions.MatchEvaluator]{param($match) $match.Value+$bootstrap},1)
}

function Invoke-DuneDockerWebInterface {
    param($Request, $Response,[ValidateSet('file-browser','director')][string]$Service)
    if ($env:DST_HOSTING_BACKEND -ne 'docker') {
        Write-DuneError -Response $Response -Status 404 -Message 'Docker hosting is not enabled.'; return
    }
    $prefix = '/api/docker/'+$Service+'/'
    $label=if($Service -eq 'director'){'Battlegroup Director'}else{'File Browser'}
    $path = [string]$Request.Url.AbsolutePath
    if (-not $path.StartsWith($prefix, [StringComparison]::Ordinal)) {
        Write-DuneError -Response $Response -Status 404 -Message "$label path not found."; return
    }
    $method = [string]$Request.HttpMethod
    $action = if ($method -in @('GET','HEAD')) { 'files.endpoint' } else { 'files.write-access' }
    $suffix=$path.Substring($prefix.Length)
    if($Service -eq 'director'){
        $staticRead=$method -in @('GET','HEAD') -and ($suffix -eq '' -or $suffix -cmatch '^(?:Script|Stylesheet|Icons)/' -or $suffix -eq 'favicon.ico')
        $action=if($staticRead){'director.endpoint'}else{'director.write-access'}
    }
    $reply = Invoke-DuneDockerManager -Request @{action=$action}
    if ($Service -eq 'file-browser' -and $reply.ok -and -not $reply.data.available -and $method -eq 'GET' -and $path -eq $prefix) {
        $reply = Invoke-DuneDockerManager -Request @{action='files.open'}
    }
    $port = 0
    if (-not $reply.ok -or -not $reply.data.available -or
        -not [int]::TryParse([string]$reply.data.port, [ref]$port) -or $port -lt 1024 -or $port -gt 65535) {
        Write-DuneError -Response $Response -Status 503 -Message "$label is unavailable. Finish any pending server operation and check the battlegroup, then reopen it from the dashboard."; return
    }
    # Build a fixed authority, never resolve a user-supplied absolute URI.
    $upstreamPath=if($Service -eq 'director'){'/'+$suffix}else{$path}
    $target = [Uri]::new(('http://127.0.0.1:{0}{1}{2}' -f $port, $upstreamPath, $Request.Url.Query))
    if ($Service -eq 'file-browser' -and -not $target.AbsolutePath.StartsWith($prefix, [StringComparison]::Ordinal)) {
        Write-DuneError -Response $Response -Status 400 -Message "Invalid $label path."; return
    }
    $handler = [Net.Http.SocketsHttpHandler]::new()
    $handler.AllowAutoRedirect = $false
    $handler.UseCookies = $false
    $handler.UseProxy = $false
    $handler.ConnectTimeout = [TimeSpan]::FromSeconds(5)
    $client = [Net.Http.HttpClient]::new($handler)
    $client.Timeout = if($Service -eq 'director'){[TimeSpan]::FromMinutes(5)}else{[Threading.Timeout]::InfiniteTimeSpan}
    $message = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::new($method), $target)
    $upstream = $null
    try {
        # The embedded UI sets its own JWT cookie for window.open downloads.
        # Forward only that cookie, never the console session or launch token.
        $fileCookie = $Request.Cookies['auth']
        if ($Service -eq 'file-browser' -and $fileCookie -and $fileCookie.Value.Length -le 16384 -and
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
            if($Service -eq 'director'){
                $resolved=[Uri]::new($target,$location)
                if($resolved.Scheme -cne 'http' -or $resolved.Host -cne '127.0.0.1' -or $resolved.Port -ne $port -or $resolved.UserInfo){
                    Write-DuneError -Response $Response -Status 502 -Message 'Battlegroup Director returned an unexpected redirect.';return
                }
                $location=$prefix.TrimEnd('/')+$resolved.AbsolutePath+$resolved.Query+$resolved.Fragment
            } elseif (-not $location.StartsWith($prefix, [StringComparison]::Ordinal)) {
                Write-DuneError -Response $Response -Status 502 -Message 'File Browser returned an unexpected redirect.'; return
            }
            $Response.Headers['Location'] = $location
        }
        if ($upstream.Content.Headers.ContentType) { $Response.ContentType = [string]$upstream.Content.Headers.ContentType }
        if($Service -eq 'director' -and $method -ne 'HEAD' -and $Response.StatusCode -notin @(204,304) -and $Response.ContentType -like 'text/html*'){
            if($upstream.Content.Headers.ContentLength -gt 2MB){Write-DuneError -Response $Response -Status 502 -Message 'The Director page exceeds the supported response size.';return}
            $html=$upstream.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            if($html.Length -gt 2MB){Write-DuneError -Response $Response -Status 502 -Message 'The Director page exceeds the supported response size.';return}
            $bytes=[Text.Encoding]::UTF8.GetBytes((ConvertTo-DuneDockerDirectorHtml -Html $html -Port $port))
            $Response.ContentType='text/html; charset=utf-8'
            $Response.ContentLength64=$bytes.Length
            $Response.OutputStream.Write($bytes,0,$bytes.Length)
            return
        }
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
        try { Write-DuneError -Response $Response -Status 502 -Message "$label connection ended. Reopen it from the dashboard and try again." } catch {}
    } finally {
        if ($upstream) { $upstream.Dispose() }
        $message.Dispose()
        $client.Dispose()
    }
}
