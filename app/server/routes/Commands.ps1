# Commands API — list catalogue (with current availability) and persist layout.

# GET /api/commands — catalogue + availability + persisted layout (3 sections).
Register-DuneRoute -Method GET -Path '/api/commands' -Handler {
    param($req, $res, $routeParams, $body)
    $state  = Get-DuneCurrentState
    $layout = Get-DuneCommandLayout
    $cmds = foreach ($c in (Get-DuneCommandCatalogue)) {
        if ($c.Hidden) { continue }
        $av = Get-DuneCommandAvailability -Command $c -State $state
        $dockerCommand = $state.hostingBackend -eq 'docker' -and $c.Name -in @('start','stop','restart','startup','shutdown','reboot','update','logs-export','operator-logs-export')
        $dockerDescriptions=@{start='Start the battlegroup containers';startup='Start the battlegroup containers';stop='Stop the battlegroup gracefully';shutdown='Stop the battlegroup gracefully';restart='Stop and start the battlegroup containers';reboot='Stop and start the battlegroup containers';'logs-export'='Download retained battlegroup container logs';'operator-logs-export'='Download retained Docker management logs'}
        @{
            section      = $c.Section   # original catalogue section, kept as a hint
            key          = $c.Key
            name         = $c.Name
            label        = $(if ($dockerCommand -and $c.Name -eq 'update' -and $state.updateRecovery) { 'Recover server update' } elseif ($c.Label) { $c.Label } else { $c.Name })
            mode         = $(if($dockerCommand){'Docker'}else{$c.Mode})
            requires     = $(if($dockerCommand){'none'}else{$c.Requires})
            disabledWhen = $c.DisabledWhen
            external     = [bool]$c.External
            desc         = $(if($dockerCommand -and $c.Name -eq 'update'){if($state.updateRecovery){'Recover the interrupted server update using its recorded operation'}else{'Stage the official package, verify a backup, migrate and update the battlegroup'}}elseif($dockerCommand){$dockerDescriptions[$c.Name]}else{$c.Desc})
            available    = $av.available
            reason       = $av.reason
        }
    }
    # Force-wrap each per-section array so PS 5.1 ConvertTo-Json emits real
    # JSON arrays even when a section is empty.
    $sectionsOut = @(
        ,([object[]]$layout.sections[0])
        ,([object[]]$layout.sections[1])
        ,([object[]]$layout.sections[2])
    )
    Write-DuneJson -Response $res -Body @{
        state        = $state
        sectionNames = $layout.sectionNames
        sections     = $sectionsOut
        commands     = $cmds
    }
}

# PUT /api/commands/layout — body: { sectionNames: ['a','b','c'], sections: [[],[],[]] }
# Replaces the persisted layout in full. Server normalizes (dedupes commands,
# trims names, parks orphan catalogue entries in section 0).
Register-DuneRoute -Method PUT -Path '/api/commands/layout' -Handler {
    param($req, $res, $routeParams, $body)
    if ($null -eq $body) {
        Write-DuneError -Response $res -Status 400 -Message 'Body required'
        return
    }

    # Body parser returns hashtables on both PS 5.1 and 7+ (see HttpServer.ps1).
    $names    = $null
    $sections = $null
    if ($body -is [System.Collections.IDictionary]) {
        if ($body.Contains('sectionNames')) { $names    = $body['sectionNames'] }
        if ($body.Contains('sections'))     { $sections = $body['sections'] }
    } else {
        if ($body.PSObject.Properties['sectionNames']) { $names    = $body.sectionNames }
        if ($body.PSObject.Properties['sections'])     { $sections = $body.sections }
    }

    if ($null -eq $names -or $null -eq $sections) {
        Write-DuneError -Response $res -Status 400 -Message 'sectionNames and sections are both required'
        return
    }

    try {
        $nameArr = @($names | ForEach-Object { "$_" })
        $secArr  = @()
        foreach ($s in $sections) {
            $secArr += ,@(@($s) | ForEach-Object { "$_" })
        }
        Save-DuneCommandLayout -SectionNames $nameArr -Sections $secArr
        $layout = Get-DuneCommandLayout
        $sectionsOut = @(
            ,([object[]]$layout.sections[0])
            ,([object[]]$layout.sections[1])
            ,([object[]]$layout.sections[2])
        )
        Write-DuneJson -Response $res -Body @{
            ok           = $true
            sectionNames = $layout.sectionNames
            sections     = $sectionsOut
        }
    } catch {
        Write-DuneError -Response $res -Status 400 -Message "Invalid layout: $($_.Exception.Message)"
    }
}

# POST /api/commands/layout/reset — drop the persisted layout file.
Register-DuneRoute -Method POST -Path '/api/commands/layout/reset' -Handler {
    param($req, $res, $routeParams, $body)
    Reset-DuneCommandLayout
    $layout = Get-DuneCommandLayout
    $sectionsOut = @(
        ,([object[]]$layout.sections[0])
        ,([object[]]$layout.sections[1])
        ,([object[]]$layout.sections[2])
    )
    Write-DuneJson -Response $res -Body @{
        ok           = $true
        sectionNames = $layout.sectionNames
        sections     = $sectionsOut
    }
}

# POST /api/commands/run/{name} — launch a command in a new console window.
# Returns immediately with { ok, pid, name, mode } — the launched process is
# detached and runs independently. Frontend can show "Launched (PID N)" toast.
Register-DuneRoute -Method POST -Path '/api/commands/run/{name}' -Handler {
    param($req, $res, $routeParams, $body)
    $name = $routeParams.name
    $cmd  = Get-DuneCommandByName -Name $name
    if (-not $cmd) {
        Write-DuneError -Response $res -Status 404 -Message "Unknown command: $name"
        return
    }

    # Docker always uses account permissions, including direct loopback requests.
    # Windows retains its host-local allowance. Keep the remote command list
    # in sync with the Commands page's REMOTE_ALLOWED set.
    $remoteAllowedCommands = @('startup', 'start', 'restart', 'start-vm', 'reboot', 'apply-inis')
    $isRemote = $env:DST_HOSTING_BACKEND -eq 'docker' -or -not (Test-DuneLocalOnlyRequest -Request $req)
    $portalRole = [string]$routeParams.portalAccountRole
    $authorizedUpdate = ($portalRole -in @('owner','admin') -and $name -in @('update','update-with-tanks'))
    $dockerOwnerCommand=($env:DST_HOSTING_BACKEND -eq 'docker' -and $portalRole -eq 'owner' -and
        $name -in @('start','stop','restart','apply-inis','update','logs-export','operator-logs-export'))
    if ($isRemote -and ($name -notin $remoteAllowedCommands) -and -not $authorizedUpdate -and -not $dockerOwnerCommand) {
        Write-DuneError -Response $res -Status 403 -Message "Command '$name' is not available remotely."
        return
    }

    # Server-side availability check — refuse if command isn't currently available.
    $state = Get-DuneCurrentState
    $av    = Get-DuneCommandAvailability -Command $cmd -State $state
    if (-not $av.available) {
        Write-DuneError -Response $res -Status 409 -Message "Command not available: $($av.reason)"
        return
    }

    $disruptiveActions = @{
        shutdown = 'stopping the battlegroup and powering off the VM'
        'stop-vm' = 'gracefully shutting down the VM and its running battlegroup'
        reboot = 'rebooting the VM and battlegroup'
        restart = 'restarting the battlegroup'
        stop = 'stopping the battlegroup'
        'apply-inis' = 'applying INI settings and restarting the battlegroup'
        update = 'updating the battlegroup'
        'update-with-tanks' = 'updating the battlegroup with Tank support'
        import = 'importing a database backup'
        'change-vm-ip' = 'changing the VM network configuration'
        'change-battlegroup-ip' = 'changing the battlegroup player IP'
    }
    if ($disruptiveActions.ContainsKey([string]$name)) {
        if (-not (Test-DuneDisruptiveActionGuard -Req $req -Res $res -Action $disruptiveActions[[string]$name])) { return }
    }

    try {
        if ($env:DST_HOSTING_BACKEND -eq 'docker') {
            if($name -in @('update','update-with-tanks')){
                $allowOnline=$false
                try{$allowOnline=($req.QueryString['force'] -in @('1','true','yes'))}catch{}
                $reply=Start-DuneDockerFuncomUpdate -AllowOnline $allowOnline -Recover:([bool]$state.updateRecovery) -WithTanks:($name -eq 'update-with-tanks')
                if(-not $reply.ok){Write-DuneError -Response $res -Status 409 -Message $reply.error;return}
                Write-DuneJson -Response $res -Body @{ok=$true;name=$name;mode='Docker';operationId=$reply.data.operation.id;started=(Get-Date).ToString('o')}
                return
            }
            if($name -in @('logs-export','operator-logs-export')){
                $scope=if($name -eq 'logs-export'){'battlegroup'}else{'operator'}
                $reply=Invoke-DuneDockerManager -Request @{action='logs.export';scope=$scope}
                if(-not $reply.ok){Write-DuneError -Response $res -Status 409 -Message $reply.error;return}
                Write-DuneJson -Response $res -Body @{ok=$true;name=$name;mode='Docker';operationId=$reply.data.operation.id;started=(Get-Date).ToString('o')}
                return
            }
            $actions=@{start='services.start';startup='services.start';stop='services.stop';shutdown='services.stop';restart='services.restart';reboot='services.restart';'apply-inis'='services.restart'}
            if (-not $actions.ContainsKey([string]$name)) { Write-DuneError -Response $res -Status 501 -Message 'This command has no Docker adapter yet.'; return }
            if($name -in @('start','startup','restart','reboot','apply-inis')){
                $result=Invoke-DuneBattlegroupRestart -Ip docker -ApplyInis:($name -eq 'apply-inis') -StartStopped:($name -in @('start','startup'))
                if(-not $result.ok){Write-DuneError -Response $res -Status 409 -Message $result.message;return}
                Write-DuneJson -Response $res -Body @{ok=$true;name=$name;mode='Docker';operationId=$result.operationId;started=(Get-Date).ToString('o')}
                return
            }
            $reply=Invoke-DuneDockerManager -Request @{action=$actions[[string]$name]}
            if (-not $reply.ok) { Write-DuneError -Response $res -Status 409 -Message $reply.error; return }
            Write-DuneJson -Response $res -Body @{ok=$true;name=$name;mode='Docker';operationId=$reply.data.operation.id;started=(Get-Date).ToString('o')}
            return
        }
        # For commands that restart the battlegroup, force-clear any orphaned
        # *_progress.running flags. Restarting the BG wipes/cycles game state,
        # so an in-flight seed or list-tick from a prior run is moot — and
        # leaving the flag set blocks fresh runs after the restart with
        # "A seed market run is already in progress."
        if ($name -in @('start','restart','startup','reboot')) {
            if (Get-Command Clear-DuneBotStaleRunFlags -ErrorAction SilentlyContinue) {
                try { Clear-DuneBotStaleRunFlags } catch {}
            }
        }

        # Retail's installed User*.ini files are authoritative. Both explicit
        # Apply INIs and a DST-initiated restart push them into the battlegroup,
        # rebuild startup values, then restart through the same guarded helper.
        if ($name -in @('apply-inis', 'restart')) {
            $ctx = Get-DuneGameConfigContext
            if (-not $ctx.ok) {
                Write-DuneError -Response $res -Status $ctx.status -Message $ctx.message
                return
            }
            $r = Invoke-WithDuneLock -Name 'retail-startup-sync' -Script {
                Invoke-DuneBattlegroupRestart -Ip $ctx.ip -ApplyInis:($name -eq 'apply-inis')
            }
            if (-not $r.ok) {
                Write-DuneError -Response $res -Status 502 -Message $r.message
                return
            }
            Write-DuneJson -Response $res -Body @{
                ok      = $true
                name    = $name
                mode    = 'InApp'
                message = $r.message
                started = (Get-Date).ToString('o')
            }
            return
        }

        $result = Invoke-DuneCommandExternal -Name $name
        Write-DuneJson -Response $res -Body $result
    } catch {
        Write-DuneError -Response $res -Status 500 -Message "Launch failed: $($_.Exception.Message)"
    }
}
