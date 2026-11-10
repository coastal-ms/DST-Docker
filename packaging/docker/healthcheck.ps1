$ErrorActionPreference = 'Stop'
try {
    $url = [uri](Get-Content -LiteralPath '/data/state/DuneServer/last-url.txt' -Raw).Trim()
    $response = Invoke-RestMethod -Uri ($url.GetLeftPart([UriPartial]::Authority) + '/api/portal-auth/status') -TimeoutSec 5
    if ($response.accountLoginEnabled -isnot [bool] -or $response.ownerSetupRequired -isnot [bool] -or $response.authenticated -isnot [bool]) { exit 1 }
    exit 0
} catch { exit 1 }
