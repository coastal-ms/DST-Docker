# One-time owner bootstrap, authorized by the installer's private launch key.
function Get-DuneDockerOwnersForHost {
    if($env:DST_HOSTING_BACKEND -ne 'docker'){throw 'Owner recovery is available on the Docker host.'}
    $setup=Get-DuneDockerOwnerSetupState
    return @{owners=@($setup.store.accounts|Where-Object {$_.role -ceq 'owner'}|ForEach-Object {@{username=[string]$_.username;enabled=[bool]$_.enabled}})}
}

function Reset-DuneDockerOwnerForHost {
    param([string]$Username,[string]$Confirmation)
    if($env:DST_HOSTING_BACKEND -ne 'docker'){throw 'Owner recovery is available on the Docker host.'}
    if($Confirmation -cne 'RESET OWNER'){throw 'Type RESET OWNER exactly to confirm the selected Owner password reset.'}
    if(-not (Test-DunePortalUsername $Username)){throw 'Supply the exact existing Owner username.'}
    return Invoke-DunePortalAuthLock {
        $store=(Get-DuneDockerOwnerSetupState).store
        $ownerCandidates=@($store.accounts|Where-Object {$_.normalizedUsername -ceq (Normalize-DunePortalUsername $Username)})
        if($ownerCandidates.Count -ne 1 -or $ownerCandidates[0].role -cne 'owner' -or [string]$ownerCandidates[0].id -cnotmatch '^[a-f0-9]{32}$'){
            throw 'Exactly one existing Owner must match that username. List Owners first; no account was changed.'
        }
        $account=$ownerCandidates[0]
        $password=New-DunePortalOneTimePassword
        $metadata=New-DunePortalPasswordHash -Password $password
        # Revoke first: a session-storage failure cannot commit an unknown new
        # password. The shared lock excludes concurrent account/login changes.
        Revoke-DunePortalSessions -AccountId ([string]$account.id)
        $now=(Get-Date).ToUniversalTime().ToString('o')
        $account.password=$metadata;$account.mustChangePassword=$true;$account.enabled=$true
        $account.failedCount=0;$account.lockoutUntil='';$account.locallyVerifiedAt=''
        $account.passwordChangedAt=$now;$account.updatedAt=$now
        $store.accountLoginEnabled=$true;$store.clientFailures=@()
        Save-DunePortalAccountStore $store
        Write-DunePortalAudit -Event 'host-owner-recovery' -Result 'success'
        return @{username=[string]$account.username;oneTimePassword=$password}
    }
}

function Get-DuneDockerOwnerSetupState {
    if($env:DST_HOSTING_BACKEND -ne 'docker'){return @{required=$false}}
    $path=Get-DunePortalAccountsPath
    if(Test-Path -LiteralPath $path){
        try{$store=ConvertTo-DunePortalHashtable (Get-Content -LiteralPath $path -Raw|ConvertFrom-Json -ErrorAction Stop)}
        catch{throw 'The existing portal account store needs review; owner setup was not reopened.'}
    }elseif(Test-Path -LiteralPath "$path.bak"){
        throw 'The existing portal account store needs review; owner setup was not reopened.'
    }else{$store=Get-DunePortalAccountStore}
    if($store.unreadable -or $store.version -ne 1 -or $store.accounts -isnot [array] -or $store.accountLoginEnabled -isnot [bool]){
        throw 'The existing portal account store needs review; owner setup was not reopened.'
    }
    return @{required=(@($store.accounts).Count -eq 0 -and -not $store.accountLoginEnabled);store=$store}
}

function New-DuneDockerOwner {
    param([string]$Username,[string]$Password,$Request)
    if($env:DST_HOSTING_BACKEND -ne 'docker' -or -not (Test-DuneLaunchToken -Request $Request)){
        throw 'Open the private installer link to create the first owner.'
    }
    if(-not (Test-DunePortalRequestOrigin -Request $Request)){throw 'Request origin rejected.'}
    if(-not (Test-DunePortalUsername $Username)){throw 'Username must be 3-64 characters using letters, numbers, spaces, dot, underscore, or hyphen.'}
    if(-not (Test-DunePortalPasswordPolicy $Password)){throw 'Password must be 12 to 128 characters.'}
    return Invoke-DunePortalAuthLock {
        $setup=Get-DuneDockerOwnerSetupState
        if(-not $setup.required){throw 'Owner setup is already complete. Sign in with an existing account.'}
        $now=(Get-Date).ToUniversalTime().ToString('o')
        $account=@{id=[guid]::NewGuid().ToString('N');username=$Username.Trim();normalizedUsername=(Normalize-DunePortalUsername $Username);
            gameCharacterId='';gameCharacterLabel='';role='owner';enabled=$true;password=(New-DunePortalPasswordHash -Password $Password);
            mustChangePassword=$false;createdAt=$now;updatedAt=$now;passwordChangedAt=$now;lastLoginAt=$now;locallyVerifiedAt=$now;failedCount=0;lockoutUntil=''}
        $store=$setup.store;$store.accounts=@($account);$store.accountLoginEnabled=$true
        Save-DunePortalAccountStore $store
        $issued=New-DunePortalSession -AccountId $account.id
        return @{account=$account;token=$issued.token}
    }
}
