$ErrorActionPreference = 'Stop'
try {
    $url = [uri](Get-Content -LiteralPath '/data/state/DuneServer/last-url.txt' -Raw).Trim()
    $response = Invoke-RestMethod -Uri ($url.GetLeftPart([UriPartial]::Authority) + '/api/ping' + $url.Query) -TimeoutSec 5
    if (-not $response.ok) { exit 1 }
    exit 0
} catch { exit 1 }
