# Keep recent immutable bundles available to browser tabs opened before an update.
function Initialize-DuneStaticAssetCache {
    param([string]$DistRoot, [string]$CacheRoot)
    $script:DuneAssetGenerations = @()
    if (-not $CacheRoot -or -not (Test-Path -LiteralPath (Join-Path $DistRoot 'index.html'))) { return }
    $root = [IO.Path]::GetFullPath($CacheRoot)
    $generation = (Get-FileHash -LiteralPath (Join-Path $DistRoot 'index.html') -Algorithm SHA256).Hash.ToLowerInvariant()
    $destination = Join-Path $root $generation
    [void][IO.Directory]::CreateDirectory($destination)
    $assets = Join-Path $DistRoot 'assets'
    if (Test-Path -LiteralPath $assets) {
        foreach ($file in Get-ChildItem -LiteralPath $assets -File) {
            if ($file.Name -cmatch '^[A-Za-z0-9_.-]+-[A-Za-z0-9_-]{6,}\.(?:js|css|woff2?|png|jpg|jpeg|svg|webp)$') {
                $target = Join-Path $destination $file.Name
                if (-not (Test-Path -LiteralPath $target)) { Copy-Item -LiteralPath $file.FullName -Destination $target -ErrorAction Stop }
            }
        }
    }
    [IO.File]::WriteAllText((Join-Path $destination '.ready'), '')
    [IO.Directory]::SetLastWriteTimeUtc($destination, [DateTime]::UtcNow)
    $generations = @(Get-ChildItem -LiteralPath $root -Directory | Where-Object { $_.Name -cmatch '^[a-f0-9]{64}$' -and (Test-Path -LiteralPath (Join-Path $_.FullName '.ready')) } | Sort-Object LastWriteTimeUtc -Descending)
    $script:DuneAssetGenerations = @($generations | Select-Object -First 5 | ForEach-Object FullName)
    foreach ($old in @($generations | Select-Object -Skip 5)) {
        # Only complete, generated directories directly inside this cache may be pruned.
        if ([IO.Path]::GetFullPath($old.Parent.FullName) -eq $root) { Remove-Item -LiteralPath $old.FullName -Recurse -Force }
    }
}

function Resolve-DuneRetainedAsset {
    param([string]$UrlPath)
    if ($UrlPath -cnotmatch '^/assets/([A-Za-z0-9_.-]+-[A-Za-z0-9_-]{6,}\.(?:js|css|woff2?|png|jpg|jpeg|svg|webp))$') { return $null }
    $name = $Matches[1]
    foreach ($directory in $script:DuneAssetGenerations) {
        $candidate = Join-Path $directory $name
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return $null
}
