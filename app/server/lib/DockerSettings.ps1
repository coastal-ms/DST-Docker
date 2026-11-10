function Invoke-DuneDockerSettingsReader {
    param([Parameter(Mandatory)][hashtable]$Request)
    $payload=switch([string]$Request.action){
        'read' {@{action='settings.read';file=$Request.file}}
        'backups.list' {@{action='settings.backups.list'}}
        'backups.inspect' {@{action='settings.backups.inspect'}}
        'backups.read' {@{action='settings.backups.read';path=$Request.path;sha256=$Request.sha256}}
        'backups.delete-checked' {@{action='settings.backups.delete-checked';files=$Request.files}}
        default {throw 'Unsupported server settings read request.'}
    }
    $reply=Invoke-DuneDockerManager -Request $payload
    if(-not $reply.ok){throw $reply.error}
    return $reply.data
}

function Read-DuneDockerSettingsFile {
    param([Parameter(Mandatory)][ValidateSet('game','engine','server')][string]$File)
    return Invoke-DuneDockerSettingsReader -Request @{action='read';file=$File}
}

function Write-DuneDockerSettingsFile {
    param([Parameter(Mandatory)][ValidateSet('game','engine','server')][string]$File,
        [Parameter(Mandatory)][AllowEmptyString()][string]$Raw,
        [Parameter(Mandatory)][string]$Revision,[bool]$ExpectedExists=$true,[switch]$Remove)
    $reply=Invoke-DuneDockerManager -Request @{action='settings.write';file=$File;raw=$Raw;revision=$Revision;expectedExists=$ExpectedExists;remove=[bool]$Remove}
    if(-not $reply.ok){throw $reply.error}
    return $reply.data
}

function Get-DuneDockerSettingsContext {
    $reply=Invoke-DuneDockerManager -Request @{action='status'}
    if(-not $reply.ok){return @{ok=$false;status=503;message=$reply.error}}
    if(-not @($reply.data.services|Where-Object {$_.component -eq 'game-1'}).Count){return @{ok=$false;status=503;message='Complete Docker Setup before editing server settings.'}}
    return @{ok=$true;ip='docker';native=$reply.data}
}

function Get-DuneDockerRetailSettingsSnapshot {
    $context=Get-DuneDockerSettingsContext
    if(-not $context.ok){return [ordered]@{available=$false;reason=$context.message;source='funcom-persistent-user-settings';target=@{available=$false}}}
    $current=Read-DuneDockerSettingsFile -File server
    $active=@($context.native.services|Where-Object {$_.component -like 'game-*' -and $_.state -notin @('exited','created')})
    $target=@{available=$true;namespace='docker';battlegroup=$context.native.projectId;pod='';persistentVolumeClaim='';
        mountPath='/srv';mountSubPath='';path='/srv/UserSettings/UserServerCustomSettings.ini';
        gamePath='/home/dune/server/DuneSandbox/Saved/Config/LinuxServer/ServerCustomSettings.ini';
        stopped=($context.native.desiredState -eq 'stopped' -and $active.Count -eq 0);serverPodCount=$active.Count;
        upstreamConfigured=$false;upstreamContent=''}
    return [ordered]@{available=$true;source='funcom-persistent-user-settings';authority='Linux UserSettings/UserServerCustomSettings.ini';
        fileExists=$current.fileExists;raw=$current.raw;fileRaw=$current.raw;revision=$current.revision;fileRevision=$current.revision;
        bytes=$current.bytes;modifiedAt=$current.modifiedAt;fileAuthority=$true;needsMigration=$false;target=$target}
}

# Targeted files are independent copies of the global file, not runtime files
# inside another map's container. Reuse the established INI writers so comments,
# unknown keys and arrays survive edits made through the structured controls.
function Get-DuneDockerMapSettingFields {
    param([string]$File,[AllowEmptyString()][string]$Raw)
    if($File -eq 'server'){
        return @((ConvertFrom-DuneRetailServerSettingsRaw -Raw $Raw).settings | ForEach-Object {
            $field=@{};foreach($key in $_.Keys){$field[$key]=$_.Item($key)}
            $field.id=$field.key
            if($field.key -eq 'PVPMode'){$field.editable=$true}
            $field
        })
    }
    $effective=Get-DuneIniEffective -Raw $Raw
    return @(foreach($group in (Get-DuneGameConfigSchemaApi)){
        foreach($field in $group.fields){
            # Complex structs/arrays retain their existing specialized editors.
            # ConsoleVariables need a distinct startup-command transaction and
            # must not be advertised as per-map INI edits.
            if($field.file -ne $File -or $field.type -notin @('bool','int','float','select','string') -or
                $field.structKey -or $field.consoleVar -or $field.key -match '(?i)password|token|secret' -or
                $field.section -eq $script:DuneGcSecSpice){continue}
            $id="$($field.section)||$($field.key)"
            $result=@{};foreach($key in $field.Keys){$result[$key]=$field[$key]}
            $result.id=$id;$result.group=$group.category;$result.editable=$true
            $result.value=if($effective.ContainsKey($id)){[string]$effective[$id]}else{''}
            $result
        }
    })
}

function Select-DuneDockerMapSamples {
    param([hashtable]$Samples,[object[]]$Services)
    $names=@($Services|ForEach-Object {[string]$_.name}|Where-Object {$_})
    $result=@{};foreach($key in $Samples.Keys){$result[$key]=$Samples[$key]}
    $result.containers=@($Samples.containers|Where-Object {[string]$_.name -cin $names})
    return $result
}

function Get-DuneDockerMapSettings {
    param([string]$Target,[ValidateSet('game','engine','server')][string]$File='server')
    $context=Get-DuneDockerSettingsContext
    if(-not $context.ok){throw $context.message}
    $targets=@(@{id='global';map='global';label='Global defaults · all maps'})+@(foreach($game in $context.native.plan.games){
        if([string]$game.map -cnotmatch '^(?:Survival|DeepDesert)_[1-9][0-9]*$'){continue}
        $name=switch([string]$game.map){'Survival_1'{'Hagga Basin'};'Overmap'{'Overmap'};'SH_Arrakeen'{'Arrakeen'};'SH_HarkoVillage'{'Harko Village'};'DeepDesert_1'{'Deep Desert'};default{([string]$game.map -replace '^(CB_Story_|DLC_Story_)','') -replace '_',' '}}
        @{id=[string]$game.partition;map=[string]$game.map;label="$name · partition $($game.partition)"}
    })
    if(-not $Target){return @{targets=$targets}}
    if($Target -cnotin @($targets|ForEach-Object {$_.id})){throw 'Choose Global defaults, a Hagga map or a Deep Desert map.'}
    $reply=Invoke-DuneDockerManager -Request @{action='map-settings.read';target=$Target;file=$File}
    if(-not $reply.ok){throw $reply.error}
    return @{targets=$targets;target=$Target;file=$File;revision=$reply.data.revision;raw=$reply.data.raw;
        overridden=$reply.data.overridden;pendingRestart=$reply.data.pendingRestart;adapterReady=$reply.data.adapterReady;running=$reply.data.running;
        fields=@(Get-DuneDockerMapSettingFields -File $File -Raw ([string]$reply.data.raw))}
}

function Save-DuneDockerMapSettings {
    param([hashtable]$Request)
    if($Request.file -notin @('game','engine','server') -or $Request.target -isnot [string] -or $Request.revision -notmatch '^[a-f0-9]{64}$'){
        throw 'Choose a map, settings group and current revision.'
    }
    if($Request.inherit -isnot [bool]){throw 'Choose whether to restore global settings.'}
    if($Request.target -ceq 'global' -and $Request.inherit){throw 'Global defaults cannot inherit another settings file.'}
    $current=Get-DuneDockerMapSettings -Target $Request.target -File $Request.file
    if($current.revision -cne $Request.revision){throw 'The selected map settings changed. Refresh before saving.'}
    $raw=[string]$current.raw
    if(-not $Request.inherit){
        if($Request.updates -isnot [hashtable] -or $Request.updates.Count -eq 0){throw 'Review at least one settings change.'}
        if($Request.file -eq 'server'){
            $updates=$Request.updates.Clone();$updates.DifficultyLevel='Custom'
            $raw=ConvertTo-DuneRetailServerSettingsUpdatedRaw -Raw $raw -Updates $updates -AllowMapPvp
        }else{
            $updates=@(foreach($id in $Request.updates.Keys){
                $field=@($current.fields|Where-Object {$_.id -ceq $id})
                if($field.Count -ne 1){throw 'This setting requires its specialized editor.'}
                $field=$field[0];$value=[string]$Request.updates[$id]
                if($value -match '[\r\n\x00]' -or $value.Length -gt 4096){throw 'Settings values must be single-line text.'}
                if($value){
                    if($field.type -in @('int','float')){
                        $number=0.0
                        if(-not [double]::TryParse($value,[Globalization.NumberStyles]::Float,[Globalization.CultureInfo]::InvariantCulture,[ref]$number) -or
                            [double]::IsNaN($number) -or [double]::IsInfinity($number) -or
                            ($field.type -eq 'int' -and $value -notmatch '^-?\d+$') -or
                            ($field.ContainsKey('min') -and $number -lt $field.min) -or ($field.ContainsKey('max') -and $number -gt $field.max)){
                            throw "Enter a supported value for $($field.label)."
                        }
                    }
                    if($field.type -eq 'bool' -and $value -notin @('True','False')){throw 'Choose True or False.'}
                    if($field.type -eq 'select' -and $value -cnotin @($field.options|ForEach-Object {$_.value})){throw 'Choose a supported option.'}
                }
                @{section=$field.section;key=$field.key;value=$value;remove=($value -eq '')}
            })
            $raw=ConvertTo-DuneIniManaged -Raw $raw -Updates $updates -QuotedKeys (Get-DuneGameConfigQuotedKeys)
        }
    }
    $reply=Invoke-DuneDockerManager -Request @{action='map-settings.write';target=$Request.target;file=$Request.file;
        revision=$Request.revision;raw=$raw;inherit=$Request.inherit}
    if(-not $reply.ok){throw $reply.error}
    return Get-DuneDockerMapSettings -Target $Request.target -File $Request.file
}
