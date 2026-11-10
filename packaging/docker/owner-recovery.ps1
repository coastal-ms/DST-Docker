param([Parameter(Mandatory)][ValidateSet('List','Reset')][string]$Action,
      [string]$Username,[string]$Confirmation)
$ErrorActionPreference='Stop'
try {
    if(-not $IsLinux -or $env:DST_HOSTING_BACKEND -ne 'docker'){throw 'Run Owner recovery from this installation on its Linux or WSL Docker host.'}
    $env:APPDATA=$env:XDG_CONFIG_HOME
    if(-not $env:APPDATA){throw 'The protected Docker configuration directory is unavailable.'}
    . /opt/dst/app/server/lib/RemoteIdentity.ps1
    . /opt/dst/app/server/lib/PortalAuth.ps1
    . /opt/dst/app/server/lib/DockerOwnerSetup.ps1
    if($Action -eq 'List'){
        $owners=(Get-DuneDockerOwnersForHost).owners
        if(-not $owners.Count){Write-Output 'No Owner exists yet. Open the private first-setup link from: sh bin/dst-docker url'}
        else{$owners|ForEach-Object {Write-Output ("{0}`t{1}" -f $(if($_.enabled){'Enabled'}else{'Disabled'}),$_.username)}}
    }else{
        $result=Reset-DuneDockerOwnerForHost -Username $Username -Confirmation $Confirmation
        Write-Output ("Owner: {0}" -f $result.username)
        Write-Output ("One-time password: {0}" -f $result.oneTimePassword)
        Write-Output 'Sign in through the console and replace this password before continuing. Owner sessions and sign-in lockouts were cleared; account sign-in remains enabled.'
    }
}catch{Write-Error $_.Exception.Message;exit 1}
