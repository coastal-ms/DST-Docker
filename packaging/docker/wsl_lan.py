"""Explicit WSL network mode and dedicated LAN-address configuration."""
import base64
import hashlib
import ipaddress
import json
import re
import select
import socket
import struct
import time
from pathlib import Path
import wsl_memory


def validate(value):
    if not isinstance(value,dict):raise ValueError('Supply the Docker network settings.')
    mode=value.get('mode')
    if mode not in {'nat','mirrored','bridged'}:raise ValueError('Choose an available Docker network mode.')
    if not isinstance(value.get('switch',''),str) or not isinstance(value.get('address',''),str):raise ValueError('Supply text for the switch and LAN address.')
    switch=value.get('switch','').strip()
    if mode=='bridged' and (not switch or len(switch)>100 or any(c in switch for c in '\r\n[];#*?') or any(ord(c)<32 for c in switch)):
        raise ValueError('Enter the existing external Hyper-V switch name.')
    address=value.get('address','').strip()
    prefix=value.get('prefix',24)
    if type(prefix) is not int or not 8<=prefix<=30:raise ValueError('Choose an IPv4 subnet prefix from 8 to 30.')
    if mode!='bridged':address=''
    if address:
        try:interface=ipaddress.IPv4Interface(f'{address}/{prefix}')
        except ValueError:raise ValueError('Enter a valid private LAN IPv4 address.') from None
        private=any(interface.ip in ipaddress.IPv4Network(cidr) for cidr in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))
        if not private or interface.ip in {interface.network.network_address,interface.network.broadcast_address}:
            raise ValueError('Choose a usable private LAN host address.')
    return {'mode':mode,'switch':switch if mode=='bridged' else '', 'address':address,'prefix':prefix}


def update_config(raw,value):
    text,encoding,bom=wsl_memory.decode(raw)
    newline='\r\n' if '\r\n' in text else '\n'
    wanted={'networkingmode':('networkingMode',value['mode']),'vmswitch':('vmSwitch',value['switch'] if value['mode']=='bridged' else None)}
    out=[];section='';written=set()
    def remaining():
        for key,(name,setting) in wanted.items():
            if key not in written and setting is not None:
                if out and not out[-1].endswith(('\r','\n')):out[-1]+=newline
                out.append(name+'='+setting+newline);written.add(key)
    for line in text.splitlines(keepends=True):
        header=re.match(r'^\s*\[([^]]+)\]',line)
        if header:
            if section=='wsl2':remaining()
            section=header[1].strip().lower()
        match=re.match(r'^\s*([A-Za-z]+)\s*=',line) if section=='wsl2' else None
        if match and match[1].lower() in wanted:
            key=match[1].lower();name,setting=wanted[key]
            if key not in written and setting is not None:out.append(name+'='+setting+newline)
            written.add(key);continue
        out.append(line)
    if section!='wsl2' and 'networkingmode' not in written:
        if out and not out[-1].endswith(('\r','\n')):out[-1]+=newline
        out.append('[wsl2]'+newline)
    remaining()
    return bom+''.join(out).encode(encoding)


def recovery_script(directory,expected_hash):
    suffix=hashlib.sha256(str(directory).encode()).hexdigest()[:12]
    restore="""$ErrorActionPreference='Stop'
$path=Join-Path $env:USERPROFILE '.wslconfig'
if((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'EXPECTED'){throw 'WSL configuration was changed outside DST. Review it before restoring.'}
[IO.File]::WriteAllBytes($path,[IO.File]::ReadAllBytes((Join-Path $PSScriptRoot 'previous.wslconfig')))
& wsl.exe --shutdown
Write-Host 'Previous WSL network configuration restored. Reopen the DST Docker desktop icon.'
""".replace('EXPECTED',expected_hash)
    return """$ErrorActionPreference='Stop'
$folder=Join-Path $env:LOCALAPPDATA 'DSTDocker\\Network\\SUFFIX'
[void][IO.Directory]::CreateDirectory($folder)
$path=Join-Path $env:USERPROFILE '.wslconfig'
$bytes=[byte[]]@();if(Test-Path -LiteralPath $path){$bytes=[IO.File]::ReadAllBytes($path)}
[IO.File]::WriteAllBytes((Join-Path $folder 'previous.wslconfig'),$bytes)
[IO.File]::WriteAllBytes((Join-Path $folder 'Restore-Network.ps1'),[Convert]::FromBase64String('SCRIPT'))
$desktop=[Environment]::GetFolderPath('Desktop')
$command=Join-Path $desktop 'Recover Docker network (SUFFIX).cmd'
$lines=@('@echo off','powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\\DSTDocker\\Network\\SUFFIX\\Restore-Network.ps1"','pause')
[IO.File]::WriteAllLines($command,$lines,[Text.Encoding]::ASCII)
Write-Output $command
""".replace('SUFFIX',suffix).replace('SCRIPT',base64.b64encode(restore.encode('utf-8-sig')).decode())


def settings(windows_script,directory,network,value=None):
    path=directory/'lan-settings.json'
    saved=json.loads(path.read_text()) if path.exists() else {'mode':network['networkingMode'],'switch':'','address':'','prefix':24}
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if value is not None:
        desired=validate(value)
        if desired['address']:
            # A dedicated WSL address must not take the Windows host's address.
            if desired['address']==network.get('windowsIp',network.get('dockerIp')):
                raise ValueError('That address belongs to Windows. Choose a separate unused LAN address.')
        record=json.loads(windows_script(wsl_memory.READ_SCRIPT));raw=base64.b64decode(record['content'])
        updated=update_config(raw,desired)
        shortcut=windows_script(recovery_script(directory,hashlib.sha256(updated).hexdigest()))
        if updated!=raw and windows_script(wsl_memory.write_script(raw,updated))!='saved':raise ValueError('The WSL network configuration was not saved.')
        from host_session import write_json
        saved={**desired,'savedBoot':boot,'configHash':hashlib.sha256(updated).hexdigest(),'recoveryShortcut':shortcut}
        write_json(path,saved)
        write_json(directory/'lan-config-recovery.json',{'previousConfig':base64.b64encode(raw).decode(),'newConfigHash':saved['configHash']})
        write_json(directory/'lan-settings-status.json',{})
    status_path=directory/'lan-settings-status.json'
    status=json.loads(status_path.read_text()) if status_path.exists() else {}
    pending=saved.get('savedBoot')==boot or saved.get('mode')!=network.get('networkingMode') or (bool(saved.get('address')) and saved['address']!=network.get('dockerIp'))
    return {'available':True,'platform':'wsl',**network,'settings':{k:saved[k] for k in ['mode','switch','address','prefix']},'restartRequired':pending,'error':status.get('error'),'recoveryShortcut':saved.get('recoveryShortcut')}


def address_in_use(interface,address,mac,seconds=1.5):
    own=bytes.fromhex(mac.replace(':',''));target=socket.inet_aton(address)
    packet=b'\xff'*6+own+b'\x08\x06'+struct.pack('!HHBBH',1,0x0800,6,4,1)+own+b'\0'*4+b'\0'*6+target
    with socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(0x0806)) as connection:
        connection.bind((interface,0));connection.send(packet)
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if not select.select([connection],[],[],max(0,deadline-time.monotonic()))[0]:break
            data=connection.recv(2048)
            if len(data)>=42 and data[12:14]==b'\x08\x06' and data[28:32]==target and data[22:28]!=own:return True
    return False


def apply(directory,run,probe=address_in_use):
    path=directory/'lan-settings.json'
    if not path.exists():return
    desired=validate(json.loads(path.read_text()))
    if desired['mode']!='bridged':return
    actual=run(['wslinfo','--networking-mode']).stdout.decode().strip().lower()
    if actual!='bridged':return
    route=json.loads(run(['ip','-j','-4','route','get','1.1.1.1']).stdout)[0]
    interface=route['dev']
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}',interface):raise ValueError('The LAN interface name is unsupported.')
    current=json.loads(run(['ip','-j','-4','address','show','dev',interface]).stdout)[0]
    owned_path=directory/'lan-address-owned.json'
    previous=json.loads(owned_path.read_text()) if owned_path.exists() else {}
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    def remove_previous():
        if previous.get('address')==desired['address']:return
        if previous.get('bootId')==boot and previous.get('interface')==interface and any(row.get('local')==previous.get('address') and row.get('label')==previous.get('label') for row in current['addr_info']):
            run(['ip','address','del',f"{previous['address']}/{previous['prefix']}",'dev',interface])
    if not desired['address']:
        remove_previous();owned_path.unlink(missing_ok=True);return
    address=ipaddress.IPv4Address(desired['address']);cidr=f"{address}/{desired['prefix']}"
    label=interface+':d'+hashlib.sha256(str(directory).encode()).hexdigest()[:4]
    if len(label)>15:raise ValueError('The LAN interface cannot use an owned address label.')
    existing=next((row for row in current['addr_info'] if row.get('local')==str(address)),None)
    if existing and existing.get('label')!=label:
        remove_previous();owned_path.unlink(missing_ok=True);return
    connected=[ipaddress.IPv4Interface(f"{row['local']}/{row['prefixlen']}").network for row in current['addr_info'] if row.get('family')=='inet']
    if ipaddress.IPv4Interface(cidr).network not in connected:raise ValueError('The dedicated IP and subnet prefix must match the LAN supplied by the selected switch.')
    if not existing:
        if probe(interface,str(address),current['address']):raise ValueError('That LAN IP is already in use. Choose another address; no address was assigned.')
        run(['ip','address','add',cidr,'dev',interface,'label',label])
    remove_previous()
    from host_session import write_json
    write_json(owned_path,{'address':str(address),'prefix':desired['prefix'],'interface':interface,'label':label,'bootId':boot})
