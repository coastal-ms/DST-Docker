function Get-DuneDockerProduct {
    param([string]$Path = (Join-Path $PSScriptRoot '../../../packaging/docker/release.json'))
    $product = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json -AsHashtable
    if($product.name -cne 'DST Docker' -or $product.repository -cne 'coastal-ms/DST-Docker' -or
        $product.version -cnotmatch '^\d+\.\d+\.\d+$' -or $product.tag -cne "v$($product.version)"){
        throw 'The DST Docker product identity is invalid.'
    }
    return $product
}
