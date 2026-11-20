$script:DuneDockerFileBrowserHandler = {
    param($req,$res,$routeParams,$body)
    Invoke-DuneDockerFileBrowser -Request $req -Response $res
}

Register-DuneRoute -Method GET -Path '/api/docker/update-progress' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    $request=@{action='updates.progress';includeOutput=($req.QueryString['output'] -eq '1')}
    if($req.QueryString['operationId']){$request.operationId=[string]$req.QueryString['operationId']}
    $reply=Invoke-DuneDockerManager -Request $request
    if(-not $reply.ok){Write-DuneError -Response $res -Status 503 -Message $reply.error;return}
    Write-DuneJson -Response $res -Body $reply.data
}

Register-DuneRoute -Method GET -Path '/api/docker/map-settings' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    try {
        $file=if($req.QueryString['file']){[string]$req.QueryString['file']}else{'server'}
        Write-DuneJson -Response $res -Body (Get-DuneDockerMapSettings -Target ([string]$req.QueryString['target']) -File $file)
    }catch{Write-DuneError -Response $res -Status 400 -Message $_.Exception.Message}
}
Register-DuneRoute -Method PUT -Path '/api/docker/map-settings' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    try {
        if($body -isnot [hashtable]){throw 'Review the selected map settings.'}
        Write-DuneJson -Response $res -Body (Save-DuneDockerMapSettings -Request $body)
    }catch{Write-DuneError -Response $res -Status 409 -Message $_.Exception.Message}
}
Register-DuneRoute -Method POST -Path '/api/docker/map-settings/restart' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    if(-not (Test-DunePlayerGuard -Req $req -Res $res -Ip 'docker')){return}
    try {
        if($body -isnot [hashtable] -or $body.target -isnot [string] -or $body.target -notmatch '^[1-9][0-9]{0,5}$'){throw 'Choose the map to restart.'}
        $reply=Invoke-DuneDockerManager -Request @{action='maps.restart';partition=[int]$body.target;force=$true}
        if(-not $reply.ok){throw $reply.error}
        Write-DuneJson -Response $res -Body $reply.data
    }catch{Write-DuneError -Response $res -Status 409 -Message $_.Exception.Message}
}
Register-DuneRoute -Method GET -Path '/api/docker/maps' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    try {
        $reply=Invoke-DuneDockerManager -Request @{action='maps.management'}
        if(-not $reply.ok){throw $reply.error}
        $samples=@{available=$false;containers=@()}
        try{$samples=Get-Content -LiteralPath '/data/docker/status.json' -Raw | ConvertFrom-Json -AsHashtable}catch{}
        $reply.data.samples=Select-DuneDockerMapSamples -Samples $samples -Services @($reply.data.metadata.services)
        $reply.data.samplesFresh=($samples.available -eq $true -and ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()-[double]$samples.observedAt) -lt 30)
        Write-DuneJson -Response $res -Body $reply.data
    }catch{Write-DuneError -Response $res -Status 503 -Message $_.Exception.Message}
}
Register-DuneRoute -Method PUT -Path '/api/docker/maps' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    try {
        if($body -isnot [hashtable]){throw 'Choose a map and setting.'}
        $request=switch([string]$body.setting){
            'mode' {@{action='maps.mode';map=$body.map;mode=$body.mode}}
            'memory' {@{action='maps.memory';map=$body.map;memoryGiB=$body.memoryGiB}}
            default {throw 'Choose map mode or memory.'}
        }
        $reply=Invoke-DuneDockerManager -Request $request
        if(-not $reply.ok){throw $reply.error}
        Write-DuneJson -Response $res -Body $reply.data
    }catch{Write-DuneError -Response $res -Status 409 -Message $_.Exception.Message}
}
Register-DuneRoute -Method POST -Path '/api/docker/maps' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    if(-not (Test-DunePlayerGuard -Req $req -Res $res -Ip 'docker')){return}
    try {
        if($body -isnot [hashtable] -or $body.target -isnot [string] -or $body.target -notmatch '^[1-9][0-9]{0,5}$' -or $body.action -notin @('start','stop','restart')){throw 'Choose a map and action.'}
        $reply=Invoke-DuneDockerManager -Request @{action=('maps.'+$body.action);partition=[int]$body.target;force=$true}
        if(-not $reply.ok){throw $reply.error}
        Write-DuneJson -Response $res -Body $reply.data
    }catch{Write-DuneError -Response $res -Status 409 -Message $_.Exception.Message}
}
Register-DuneRoute -Method GET -Path '/api/docker/file-browser/{path*}' -StreamBody -Handler $script:DuneDockerFileBrowserHandler
Register-DuneRoute -Method HEAD -Path '/api/docker/file-browser/{path*}' -StreamBody -Handler $script:DuneDockerFileBrowserHandler
Register-DuneRoute -Method POST -Path '/api/docker/file-browser/{path*}' -StreamBody -Handler $script:DuneDockerFileBrowserHandler
Register-DuneRoute -Method PUT -Path '/api/docker/file-browser/{path*}' -StreamBody -Handler $script:DuneDockerFileBrowserHandler
Register-DuneRoute -Method PATCH -Path '/api/docker/file-browser/{path*}' -StreamBody -Handler $script:DuneDockerFileBrowserHandler
Register-DuneRoute -Method DELETE -Path '/api/docker/file-browser/{path*}' -StreamBody -Handler $script:DuneDockerFileBrowserHandler

$script:DuneDockerDirectorHandler={param($req,$res,$routeParams,$body) Invoke-DuneDockerDirector -Request $req -Response $res}
Register-DuneRoute -Method GET -Path '/api/docker/director/{path*}' -StreamBody -Handler $script:DuneDockerDirectorHandler
Register-DuneRoute -Method HEAD -Path '/api/docker/director/{path*}' -StreamBody -Handler $script:DuneDockerDirectorHandler
Register-DuneRoute -Method POST -Path '/api/docker/director/{path*}' -StreamBody -Handler $script:DuneDockerDirectorHandler
Register-DuneRoute -Method PUT -Path '/api/docker/director/{path*}' -StreamBody -Handler $script:DuneDockerDirectorHandler
Register-DuneRoute -Method PATCH -Path '/api/docker/director/{path*}' -StreamBody -Handler $script:DuneDockerDirectorHandler
Register-DuneRoute -Method DELETE -Path '/api/docker/director/{path*}' -StreamBody -Handler $script:DuneDockerDirectorHandler

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

Register-DuneRoute -Method GET -Path '/api/docker/memory-swap' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    $reply=Invoke-DuneDockerManager -Request @{action='memory-swap.status'}
    if(-not $reply.ok){Write-DuneError -Response $res -Status 503 -Message $reply.error;return}
    Write-DuneJson -Response $res -Body $reply.data
}

Register-DuneRoute -Method PUT -Path '/api/docker/memory-swap' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    if($body -isnot [hashtable]){Write-DuneError -Response $res -Status 400 -Message 'Review and confirm Memory Swap settings.';return}
    $reply=Invoke-DuneDockerManager -Request @{action='memory-swap.set';enabled=$body.enabled;perServerGiB=$body.perServerGiB;poolGiB=$body.poolGiB;swappiness=$body.swappiness;confirmation=$body.confirmation}
    if(-not $reply.ok){Write-DuneError -Response $res -Status 409 -Message $reply.error;return}
    Write-DuneJson -Response $res -Body $reply.data
}

Register-DuneRoute -Method POST -Path '/api/docker/memory-swap/recover' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    if($body -isnot [hashtable]){Write-DuneError -Response $res -Status 400 -Message 'Review Memory Swap recovery.';return}
    $reply=Invoke-DuneDockerManager -Request @{action='memory-swap.recover';restorePrevious=$body.restorePrevious;confirmation=$body.confirmation}
    if(-not $reply.ok){Write-DuneError -Response $res -Status 409 -Message $reply.error;return}
    Write-DuneJson -Response $res -Body $reply.data
}

Register-DuneRoute -Method GET -Path '/api/docker/log-exports/{id}' -Handler {
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

Register-DuneRoute -Method GET -Path '/api/docker/backup-exports/{id}' -Handler {
    param($req,$res,$routeParams,$body)
    $id=[string]$routeParams.id
    if($env:DST_HOSTING_BACKEND -ne 'docker' -or $id -cnotmatch '^[a-f0-9]{32}$'){
        Write-DuneError -Response $res -Status 404 -Message 'Backup export not found.';return
    }
    $path=Join-Path '/control/backup-exports' ($id+'.backup')
    if(-not (Get-Item -LiteralPath $path -ErrorAction SilentlyContinue)){
        $path=Join-Path '/control/backup-exports' ($id+'.dump')
    }
    $file=Get-Item -LiteralPath $path -ErrorAction SilentlyContinue
    if(-not $file -or $file.PSIsContainer -or $file.LinkType){Write-DuneError -Response $res -Status 404 -Message 'This prepared download is unavailable or expired. Prepare it again from Database.';return}
    $metadata=Invoke-DuneDockerManager -Request @{action='backups.export.filename';id=$id}
    $filename=[string]$metadata.data.filename
    if(-not $metadata.ok -or $filename -cnotmatch '^(?:backup-[0-9]+-[a-f0-9]{8}|sh-[a-z0-9][a-z0-9-]{0,52}-[a-z]{6}-[0-9]{8}-[0-9]{6})\.backup$'){
        Write-DuneError -Response $res -Status 404 -Message 'This prepared download is unavailable or expired. Prepare it again from Database.';return
    }
    $res.Headers['Content-Disposition']='attachment; filename="' + $filename + '"'
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

Register-DuneRoute -Method GET -Path '/api/docker/network/public-ip' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    $address=Get-DunePublicIp
    if(-not (Test-DunePublicIPv4 -Ip $address).ok){Write-DuneError -Response $res -Status 503 -Message 'Could not detect a public IPv4 address. Enter it manually or retry.';return}
    Write-DuneJson -Response $res -Body @{publicIp=$address}
}

Register-DuneRoute -Method GET -Path '/api/docker/network' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    $addresses=Get-DuneDockerNetworkAddresses
    if(Test-DuneDockerWslHost){
        $publicIp=[string]$req.QueryString['publicIp']
        if($publicIp -and -not (Test-DunePublicIPv4 -Ip $publicIp).ok){Write-DuneError -Response $res -Status 400 -Message 'Choose a public IPv4 address for loopback status.';return}
        $reply=Invoke-DuneDockerManager -HostSession -Request @{action='network.get';publicIp=$publicIp}
        if($reply.ok){$addresses=$reply.data}
        else {
            # Browser setup is available before the desktop hosting session.
            # Host networking already exposes the current WSL route address;
            # don't substitute an old cached address or a public/loopback IP.
            $addresses=Get-DuneDockerNetworkAddresses -LocalOnly
            $private=$false
            if(Test-DuneIPv4Literal -Ip ([string]$addresses.dockerIp)){
                $bytes=([Net.IPAddress]::Parse([string]$addresses.dockerIp)).GetAddressBytes()
                $private=$bytes[0] -eq 10 -or ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or ($bytes[0] -eq 192 -and $bytes[1] -eq 168)
            }
            if($publicIp -or -not $private){Write-DuneError -Response $res -Status 503 -Message 'Open DST Docker using its desktop icon to detect the Docker host address.';return}
        }
    }
    Write-DuneJson -Response $res -Body $addresses
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
    if ($result.ok -and $result.data.backupMirror.folder) {
        $result.data.backupMirror.windowsFolder=Get-DuneDockerWindowsMirrorPath -Folder ([string]$result.data.backupMirror.folder)
    }
    Write-DuneJson -Response $res -Body $result
}

Register-DuneRoute -Method POST -Path '/api/docker/setup' -Handler {
    param($req, $res, $routeParams, $body)
    if ($env:DST_HOSTING_BACKEND -ne 'docker') { Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.'; return }
    $action = [string]$body.action
    if ($action -notin @('network.set','database.create','database.initialize','database.migrate','database.start','database.stop','world.configure','credentials.save','connections.prepare','services.prepare','services.start','services.stop','games.refresh-adapters','backups.create','backups.verify','backups.restore','backups.cleanup.recover','backups.export','backups.schedule.recover','backups.mirror.set','backups.mirror.sync','backups.mirror.recover','backups.mirror.cancel','world-restart.apply','world-restart.recover','world-restart.rollback','world-restart.research-audit','world-restart.research','world-restart.research-recover')) {
        Write-DuneError -Response $res -Status 400 -Message 'Unsupported setup action.'; return
    }
    $request = @{action=$action}
    if($action -eq 'network.set' -and $body.mode -ceq 'private' -and [string]$body.address -cne [string](Get-DuneDockerNetworkAddresses).dockerIp){
        Write-DuneError -Response $res -Status 400 -Message 'Private access must use the detected Docker address. Assign a different IP in Docker LAN address first.';return
    }
    if ($action -in @('world-restart.apply','world-restart.rollback','world-restart.research')) { $request.confirmation=[string]$body.confirmation }
    if ($action -eq 'world-restart.research') {
        if ($body.characterName -isnot [string] -or $body.characterName.Length -gt 200 -or $body.funcomId -isnot [string] -or $body.funcomId.Length -gt 200 -or @($body.itemKeys).Count -notin 1..500 -or @($body.itemKeys | Where-Object {$_ -isnot [string] -or $_.Length -gt 200}).Count) {
            Write-DuneError -Response $res -Status 400 -Message 'Choose bounded research mismatches for one character.'; return
        }
        $request.characterName=$body.characterName; $request.funcomId=$body.funcomId; $request.itemKeys=@($body.itemKeys)
    }
    if ($action -in @('network.set','services.stop','backups.restore','games.refresh-adapters')) {
        $description = if($action -eq 'backups.restore'){'restoring the battlegroup database'}else{'stopping the battlegroup'}
        if (-not (Test-DuneDisruptiveActionGuard -Req $req -Res $res -Action $description)) { return }
    }
    if ($action -eq 'database.create') {
        $port=0
        if (-not [int]::TryParse([string]$body.port,[ref]$port)) { Write-DuneError -Response $res -Status 400 -Message 'Choose a database port.'; return }
        $request.port=$port
    }
    if ($action -eq 'backups.mirror.set') { $request.enabled=$body.enabled }
    if ($action -eq 'credentials.save') { $request.token=[string]$body.token }
    if ($action -eq 'world.configure') { $request.profile=$body.profile }
    if ($action -eq 'network.set') { $request.mode=$body.mode; $request.address=$body.address; $request.expectedAddress=$body.expectedAddress }
    if ($action -in @('backups.verify','backups.restore','backups.export')) { $request.backupId=[string]$body.backupId }
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

Register-DuneRoute -Method POST -Path '/api/docker/backup-import' -StreamBody -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    $upload=$null
    try{
        if($req.Headers['Content-Type'] -notlike 'application/octet-stream*'){throw 'Send one PostgreSQL custom backup file.'}
        $originalFilename=[uri]::UnescapeDataString([string]$req.Headers['X-Dst-Backup-Filename'])
        $upload=Receive-DuneDockerBackupUpload -Stream $req.InputStream -Length $req.ContentLength64 -TrustedSource:($req.Headers['X-Dst-Trusted-Backup'] -ceq 'true') -OriginalFilename $originalFilename
        $reply=Invoke-DuneDockerManager -Request (@{action='backups.import'}+$upload)
        if(-not $reply.ok){Write-DuneJson -Response $res -Status 409 -Body @{error=$reply.error;upload=$upload;message='The separate upload was retained. Refresh Database to check for a recorded import before retrying.'};return}
        Write-DuneJson -Response $res -Body @{ok=$true;uploadId=$upload.uploadId;data=$reply.data}
    }catch{
        Write-DuneError -Response $res -Status 400 -Message $_.Exception.Message
    }
}

Register-DuneRoute -Method GET -Path '/api/docker/host' -Handler {
    param($req,$res,$routeParams,$body)
    try {
        $action=switch -CaseSensitive ($req.QueryString['detail']) {'memory' {'memory.get'} 'network' {'network.settings.get'} 'loopback' {'loopback.get'} default {'status'}}
        if($action -eq 'loopback.get' -and -not (Test-DuneDockerWslHost)){
            Write-DuneJson -Response $res -Body @{available=$false;platform='linux';message='Same-PC loopback settings require a Windows WSL host.'};return
        }
        $reply=Invoke-DuneDockerManager -HostSession -Request @{action=$action;publicIp=$req.QueryString['publicIp']}
        if(-not $reply.ok){
            $platform=if(Test-DuneDockerWslHost){'wsl'}else{'linux'}
            Write-DuneJson -Response $res -Body @{available=$false;platform=$platform;message=$reply.error};return
        }
        Write-DuneJson -Response $res -Body $reply.data
    }catch{Write-DuneError -Response $res -Status 503 -Message 'DST host session is unavailable.'}
}
Register-DuneRoute -Method POST -Path '/api/docker/host' -Handler {
    param($req,$res,$routeParams,$body)
    try {
        if($body -isnot [hashtable] -or $body.action -cnotin @('shortcut','shutdown','memory.set','network.settings.set','loopback.set')){throw 'Choose a supported host action.'}
        if($body.action -ceq 'memory.set' -and (-not $body.ContainsKey('memoryGiB') -or ($null -ne $body.memoryGiB -and $body.memoryGiB -isnot [int] -and $body.memoryGiB -isnot [long]))){throw 'Choose a whole RAM limit in GiB or the WSL default.'}
        $reply=Invoke-DuneDockerManager -HostSession -Request @{action=$body.action;confirmation=$body.confirmation;memoryGiB=$body.memoryGiB;settings=$body.settings;publicIp=$body.publicIp;target=$body.target;expectedTarget=$body.expectedTarget}
        if(-not $reply.ok){throw $reply.error}
        Write-DuneJson -Response $res -Body $reply.data
    }catch{Write-DuneError -Response $res -Status 409 -Message $_.Exception.Message}
}

Register-DuneRoute -Method GET -Path '/api/docker/tailscale' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    $reply=Invoke-DuneDockerManager -Request @{action='tailscale.get';port=(Get-DuneDockerListenerPort)}
    if(-not $reply.ok){Write-DuneError -Response $res -Status 503 -Message $reply.error;return}
    Write-DuneJson -Response $res -Body $reply.data
}
Register-DuneRoute -Method PUT -Path '/api/docker/tailscale' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    $reply=Invoke-DuneDockerManager -Request @{action='tailscale.set';mode=$body.mode;port=(Get-DuneDockerListenerPort)}
    if(-not $reply.ok){Write-DuneError -Response $res -Status 400 -Message $reply.error;return}
    Write-DuneJson -Response $res -Body $reply.data
}
Register-DuneRoute -Method GET -Path '/api/map/remote-link' -Handler {
    param($req,$res,$routeParams,$body)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){Write-DuneError -Response $res -Status 404 -Message 'Docker hosting is not enabled.';return}
    $reply=Invoke-DuneDockerManager -Request @{action='tailscale.link'}
    if(-not $reply.ok){Write-DuneError -Response $res -Status 503 -Message $reply.error;return}
    Write-DuneJson -Response $res -Body $reply.data
}
