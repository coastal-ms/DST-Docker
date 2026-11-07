# One-time owner bootstrap, authorized by the installer's private launch key.
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
