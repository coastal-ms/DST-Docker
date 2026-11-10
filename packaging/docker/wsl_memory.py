"""Preserve the Windows user's WSL settings while editing its RAM ceiling."""
import base64
import hashlib
import json
import re

GIB=1024**3
READ=object()
WINDOWS_PATH="$path=Join-Path $env:USERPROFILE '.wslconfig'"
READ_SCRIPT="""$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
PATH_LINE
$bytes=[byte[]]@();if(Test-Path -LiteralPath $path){$bytes=[IO.File]::ReadAllBytes($path)}
if($bytes.Length -gt 1048576){throw 'WSL configuration is too large.'}
@{content=[Convert]::ToBase64String($bytes);physicalBytes=[double](Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory}|ConvertTo-Json -Compress
""".replace('PATH_LINE',WINDOWS_PATH)

def decode(raw):
    for bom,encoding in ((b'\xff\xfe','utf-16-le'),(b'\xfe\xff','utf-16-be'),(b'\xef\xbb\xbf','utf-8')):
        if raw.startswith(bom):return raw[len(bom):].decode(encoding),encoding,bom
    try:return raw.decode('utf-8'),'utf-8',b''
    except UnicodeDecodeError:return raw.decode('cp1252'),'cp1252',b''

def memory_value(text):
    section='';value=None
    for line in text.splitlines():
        match=re.match(r'^\s*\[([^]]+)\]',line)
        if match:section=match[1].strip().lower()
        elif section=='wsl2':
            match=re.match(r'^\s*memory\s*=\s*([^#;]*)',line,re.I)
            if match:value=match[1].strip()
    return value

def memory_gib(value):
    if value is None:return None
    match=re.fullmatch(r'(\d+)\s*(B|KB|MB|GB|TB)?',value,re.I)
    if not match:return None
    return int(match[1])*{'B':1,'KB':1024,'MB':1024**2,'GB':GIB,'TB':1024**4}[str(match[2] or 'B').upper()]/GIB

def update_config(raw,memory):
    text,encoding,bom=decode(raw)
    newline='\r\n' if '\r\n' in text else '\n'
    result=[];section='';written=False
    for line in text.splitlines(keepends=True):
        header=re.match(r'^\s*\[([^]]+)\]',line)
        if header:
            if section=='wsl2' and not written and memory is not None:
                if result and not result[-1].endswith(('\r','\n')):result[-1]+=newline
                result.append(f'memory={memory}GB'+newline);written=True
            section=header[1].strip().lower()
        setting=re.match(r'^(\s*memory\s*=\s*)([^#;\r\n]*)([^\r\n]*)(\r?\n)?$',line,re.I) if section=='wsl2' else None
        if setting:
            if memory is not None and not written:
                comment=(' '+setting[3]) if setting[3] else ''
                result.append(setting[1]+f'{memory}GB'+comment+(setting[4] or ''));written=True
            continue
        result.append(line)
    if memory is not None and not written:
        if result and not result[-1].endswith(('\r','\n')):result[-1]+=newline
        if section!='wsl2':result.append('[wsl2]'+newline)
        result.append(f'memory={memory}GB'+newline)
    return bom+''.join(result).encode(encoding)

def write_script(previous,updated):
    return """$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
PATH_LINE
$old=[byte[]]@();if(Test-Path -LiteralPath $path){$old=[IO.File]::ReadAllBytes($path)}
if([Convert]::ToBase64String($old) -cne 'OLD'){throw 'WSL configuration changed. Refresh and save again.'}
$bytes=[Convert]::FromBase64String('NEW')
$temp=$path+'.dst-'+[guid]::NewGuid().ToString('N')
try{
 [IO.File]::WriteAllBytes($temp,$bytes)
 if(Test-Path -LiteralPath $path){[IO.File]::Replace($temp,$path,[NullString]::Value)}else{[IO.File]::Move($temp,$path)}
 if([Convert]::ToBase64String([IO.File]::ReadAllBytes($path)) -cne 'NEW'){throw 'WSL configuration could not be verified.'}
}finally{if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp}}
Write-Output 'saved'
""".replace('PATH_LINE',WINDOWS_PATH).replace('OLD',base64.b64encode(previous).decode()).replace('NEW',base64.b64encode(updated).decode())

def settings(windows_script,directory,current_bytes,boot_id,memory=READ):
    record=json.loads(windows_script(READ_SCRIPT));raw=base64.b64decode(record['content'])
    physical=int(record['physicalBytes']);maximum=max(1,physical//GIB)
    marker=directory/'wsl-memory-pending.json'
    if memory is not READ:
        if memory is not None and (type(memory) is not int or not 1<=memory<=maximum):raise ValueError(f'Choose a whole number from 1 to {maximum} GiB, or use the WSL default.')
        updated=update_config(raw,memory)
        if updated!=raw:
            if windows_script(write_script(raw,updated))!='saved':raise ValueError('WSL RAM limit was not saved.')
            raw=updated
            from host_session import write_json
            write_json(marker,{'bootId':boot_id,'sha256':hashlib.sha256(raw).hexdigest()})
    pending=json.loads(marker.read_text()) if marker.exists() else {}
    value=memory_value(decode(raw)[0])
    return {'available':True,'platform':'wsl','configuredGiB':memory_gib(value),'configuredValue':value,'useDefault':value is None,'currentMemoryGiB':current_bytes/GIB,'defaultMemoryGiB':physical/GIB/2,'maxMemoryGiB':maximum,'restartRequired':pending.get('bootId')==boot_id and pending.get('sha256')==hashlib.sha256(raw).hexdigest()}
