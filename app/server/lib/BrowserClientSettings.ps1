# Pure projection/transformation for files explicitly selected in the browser.
# No server filesystem paths are accepted or written by this adapter.
function Convert-DuneBrowserClientSettings {
    param([Parameter(Mandatory)][hashtable]$Request)
    $mode=if($Request.mode){[string]$Request.mode}else{'inspect'}
    if($mode -notin @('inspect','apply','disable-engine')){throw 'Choose a supported client-file operation.'}
    foreach($flag in @('download','reviewedRaw','approved')){
        if($Request.ContainsKey($flag) -and $Request[$flag] -isnot [bool]){throw 'Client-file approval and delivery flags must be JSON booleans.'}
    }
    if($Request.selected -isnot [bool] -or $Request.engineEnabled -isnot [bool]){throw 'Client selection and Engine.ini management must be JSON booleans.'}
    $label=if($Request.selected){[string]$Request.directory}else{'Choose this PC''s client config folder'}
    if($label.Length -gt 128 -or $label -match '[\x00-\x1f]'){throw 'Invalid browser folder label.'}
    if($mode -ne 'inspect' -and (-not $Request.selected -or $Request.approved -ne $true)){throw 'Choose your client files and review these changes before applying.'}
    $original=@{};$exists=@{}
    foreach($file in @('game','engine')){
        $entry=$Request.files[$file]
        if($entry -isnot [hashtable] -or $entry.raw -isnot [string] -or $entry.exists -isnot [bool]){throw 'Supply Game.ini and Engine.ini file records.'}
        if([Text.Encoding]::UTF8.GetByteCount($entry.raw) -gt 1MB -or $entry.raw.Contains([char]0)){throw 'Each client INI must be UTF-8 text no larger than 1 MiB.'}
        $original[$file]=[string]$entry.raw;$exists[$file]=[bool]$entry.exists
    }
    $updates=New-Object 'System.Collections.Generic.List[object]'
    if($mode -eq 'disable-engine'){
        foreach($field in $script:DuneGameConfigSchema){
            $owned=($field.ClientApply -eq $true) -or ($field.Section -eq $script:DuneGcSecConsole -and $field.Key -notlike 'Bgd.*')
            if($field.File -eq 'engine' -and $owned -and $original.engine -match ('(?m)^\s*'+[regex]::Escape($field.Key)+'\s*=')){
                $updates.Add(@{file='engine';section=$field.Section;key=$field.Key;value='';remove=$true})
            }
        }
    }elseif($mode -eq 'apply'){
        if(@($Request.updates).Count -lt 1 -or @($Request.updates).Count -gt 256){throw 'Review between 1 and 256 client setting changes.'}
        foreach($update in @($Request.updates)){
            if($update -isnot [hashtable]){throw 'Invalid client setting change.'}
            $file=[string]$update.file;$section=[string]$update.section;$key=[string]$update.key
            if($file -notin @('game','engine') -or -not $section.Trim() -or $section -match '[\[\]]' -or
                $key -notmatch '^[^=;+\-\[\]\s][^=;\[\]]*$' -or -not (Test-DuneGameConfigRawTextSafe $section) -or
                -not (Test-DuneGameConfigRawTextSafe $key) -or (Test-DuneGameConfigRawTargetBlocked -File $file -Section $section -Key $key)){
                throw 'Invalid or blocked client INI target.'
            }
            if($Request.reviewedRaw -ne $true){
                $field=@($script:DuneGameConfigSchema|Where-Object {$_.File -eq $file -and $_.Section -ceq $section -and $_.Key -ceq $key -and $_.ClientApply -eq $true})
                if($field.Count -ne 1 -or ($file -eq 'engine' -and -not $Request.engineEnabled)){throw 'This client setting is not approved for compatibility apply.'}
            }
            $clean=@{file=$file;section=$section;key=$key}
            if($update.ContainsKey('arrayLines')){
                $lines=@($update.arrayLines)
                if($lines.Count -gt 1024){throw 'Too many client INI array entries.'}
                foreach($line in $lines){if($line -isnot [string] -or -not (Test-DuneGameConfigRawTextSafe $line) -or -not (Test-DuneGameConfigArrayLineMatchesKey -Line $line -Key $key)){throw 'Invalid client INI array entry.'}}
                $clean.arrayLines=$lines;$clean.arrayRemove=($lines.Count -eq 0)
            }
            if($update.ContainsKey('value') -or -not $update.ContainsKey('arrayLines')){
                if($update.value -isnot [string] -or -not (Test-DuneGameConfigRawTextSafe $update.value)){throw 'Invalid client INI scalar value.'}
                $clean.value=$update.value;$clean.remove=($update.remove -eq $true -or [string]::IsNullOrWhiteSpace($update.value))
            }
            $updates.Add($clean)
        }
    }
    $bundles=@{};$changes=@{};$quoted=Get-DuneGameConfigQuotedKeys
    foreach($file in @('game','engine')){
        $selected=@($updates|Where-Object file -eq $file);$raw=$original[$file]
        if($selected.Count){
            Assert-DuneLabPathsUnchanged -Raw $raw -Updates $selected
            $defaults=''
            if($file -eq 'game' -and ((Test-DuneUpdatesHaveStructMember -Updates $selected) -or (Test-DuneUpdatesHaveSpicefieldMember -Updates $selected))){
                $context=Get-DuneGameConfigContext
                if(-not $context.ok){throw 'The server defaults are unavailable for this structured setting.'}
                $defaults=[string](Get-DuneGameConfigDefaults -Ip $context.ip).game
            }
            $folded=Convert-DuneSpicefieldUpdates -Raw $raw -Updates $selected -DefaultsRaw $defaults
            $folded=Convert-DuneStructUpdates -Raw $raw -Updates $folded -DefaultsRaw $defaults
            $raw=ConvertTo-DuneIniManaged -Raw $raw -Updates $folded -QuotedKeys $quoted
            $raw=$raw -replace "`r?`n","`r`n"
        }
        $name=if($file -eq 'game'){'Game.ini'}else{'Engine.ini'}
        $bundles[$file]=@{file=$file;path=$name;exists=($exists[$file] -or $selected.Count -gt 0);raw=$raw;
            sections=@(ConvertTo-DuneIniSectionsApi -Raw $raw);effective=(Get-DuneIniEffective -Raw $raw);
            effectiveByKey=(Get-DuneIniEffectiveByKey -Raw $raw);managedSections=@(Get-DuneIniManagedSectionNames -Raw $raw)}
        if($raw -cne $original[$file]){$changes[$file]=@{before=$original[$file];after=$raw;created=(-not $exists[$file]);applied=$selected.Count}}
    }
    $client=@{};foreach($key in $bundles.game.Keys){$client[$key]=$bundles.game[$key]}
    $client.dir=$label;$client.dirResolved=$label;$client.dirExists=$Request.selected
    $client.default='%LOCALAPPDATA%\DuneSandbox\Saved\Config\Windows';$client.engineEnabled=$Request.engineEnabled
    $client.game=$bundles.game;$client.engine=$bundles.engine
    $result=@{ok=$true;client=$client;changes=$changes;applied=$updates.Count;removed=$(if($mode -eq 'disable-engine'){$updates.Count}else{0})}
    if($Request.download -eq $true -and $mode -ne 'inspect'){
        $result.download=New-DuneBrowserClientDownload -Request $Request -Changes $changes
    }
    return $result
}

# Portable browser delivery. Originals are verified byte-for-byte against the
# reviewed UTF-8 text; no server or player filesystem path is opened or written.
function New-DuneBrowserClientDownload {
    param([hashtable]$Request,[hashtable]$Changes)
    $files=New-Object 'System.Collections.Generic.List[object]'
    $utf8=[Text.UTF8Encoding]::new($false,$true)
    foreach($key in @('game','engine')){
        if(-not $Changes.ContainsKey($key)){continue}
        $name=if($key -eq 'game'){'Game.ini'}else{'Engine.ini'}
        $original=$null;$bom=$false
        if($Request.files[$key].exists){
            $encoded=$Request.files[$key].bytes
            if($encoded -isnot [string] -or $encoded.Length -gt 1400000){throw 'Supply the exact original client file bytes for the download backup.'}
            try{$original=[Convert]::FromBase64String($encoded)}catch{throw 'The original client file encoding is invalid.'}
            if($original.Length -gt 1MB){throw 'Each original client file must be no larger than 1 MiB.'}
            try{$text=$utf8.GetString($original)}catch{throw 'The selected client file must use UTF-8 text.'}
            $bom=$original.Length -ge 3 -and $original[0] -eq 239 -and $original[1] -eq 187 -and $original[2] -eq 191
            if($bom){$text=$text.Substring(1)}
            if($text -cne [string]$Request.files[$key].raw){throw 'The original client bytes do not match the reviewed text. Select the files again.'}
        }
        [byte[]]$updated=$utf8.GetBytes([string]$Changes[$key].after)
        if($bom){$updated=[byte[]](@(239,187,191)+@($updated))}
        if($updated.Length -gt 1MB){throw 'The updated client file would exceed 1 MiB.'}
        $files.Add(@{name=$name;original=$original;updated=$updated})
    }
    if($files.Count -eq 0){return $null}
    $memory=[IO.MemoryStream]::new()
    try{
    $archive=[IO.Compression.ZipArchive]::new($memory,[IO.Compression.ZipArchiveMode]::Create,$true)
    $manifest=New-Object 'System.Collections.Generic.List[object]'
    try{
        foreach($file in $files){
            $record=@{name=$file.name;updated='Updated/'+$file.name;original=$null;originalSha256=$null;updatedSha256=$null}
            foreach($kind in @('original','updated')){
                [byte[]]$bytes=$file[$kind]
                if($null -eq $file[$kind]){continue}
                $path=if($kind -eq 'original'){'Originals/'+$file.name}else{'Updated/'+$file.name}
                $entry=$archive.CreateEntry($path)
                $stream=$entry.Open()
                try{$stream.Write($bytes,0,$bytes.Length)}finally{$stream.Dispose()}
                $sha=[Security.Cryptography.SHA256]::Create()
                try{$hash=([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
                $record[$kind]=$path;$record[$kind+'Sha256']=$hash
            }
            $manifest.Add($record)
        }
        $documents=@{
            'manifest.json'=(@{format=1;delivery='manual';files=@($manifest.ToArray())}|ConvertTo-Json -Depth 5)
            'README.txt'="These client files have NOT been installed automatically.`r`nClose Dune: Awakening before installing them.`r`nKeep this ZIP: Originals contains exact backups of existing files; manifest.json records their SHA256 hashes.`r`nIf the originals changed after you selected them, select the current files again and regenerate this package.`r`nCopy only the files in Updated into the same Dune client config folder you selected the originals from.`r`nRe-select the installed files in DST to inspect and verify them. Restart the game to test.`r`nThis package does not change the server or other players' files.`r`n"
        }
        foreach($name in $documents.Keys){
            $entry=$archive.CreateEntry($name);$stream=$entry.Open()
            try{$bytes=$utf8.GetBytes($documents[$name]);$stream.Write($bytes,0,$bytes.Length)}finally{$stream.Dispose()}
        }
    }finally{$archive.Dispose()}
    return @{filename='DST-client-settings.zip';base64=[Convert]::ToBase64String($memory.ToArray());files=$files.Count}
    }
    finally{$memory.Dispose()}
}
