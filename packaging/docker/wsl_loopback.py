"""Explicit, compare-and-set Windows public-IP host route changes."""
import base64
import ipaddress
import json


def public_address(value):
    try: address=ipaddress.IPv4Address(value)
    except (ValueError,TypeError): raise ValueError('Enter a public IPv4 address.') from None
    if not address.is_global or address.is_multicast: raise ValueError('Enter a public IPv4 address.')
    return str(address)


def private_address(value):
    if value is None: return None
    try: address=ipaddress.IPv4Address(value)
    except (ValueError,TypeError): raise ValueError('Choose a private IPv4 loopback target.') from None
    if not any(address in ipaddress.IPv4Network(cidr) for cidr in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):
        raise ValueError('Choose a private IPv4 loopback target.')
    return str(address)


def validate(request):
    if request.get('confirmation')!='CHANGE LOOPBACK TARGET': raise ValueError('Confirm the loopback route change.')
    if not all(key in request for key in ('publicIp','target','expectedTarget')): raise ValueError('Supply the current and requested loopback targets.')
    return {'publicIp':public_address(request['publicIp']),'target':private_address(request['target']),'expectedTarget':private_address(request['expectedTarget'])}


def snapshot(windows_script,public_ip):
    address=public_address(public_ip)
    result=json.loads(windows_script("$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"+
        "$routes=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '"+address+"/32' -ErrorAction SilentlyContinue | Sort-Object RouteMetric);"+
        "$local=@(Get-NetIPAddress -AddressFamily IPv4 | Select-Object -ExpandProperty IPAddress);"+
        "@{publicIp='"+address+"';target=$(if($routes.Count){$routes[0].NextHop}else{$null});multiple=($routes.Count -gt 1);windowsAddresses=$local}|ConvertTo-Json -Compress"))
    return {'available':True,'platform':'wsl',**result}


ROUTE_FUNCTION=r"""
function Set-DstDockerLoopbackRoute {
 param([string]$PublicIp,[AllowNull()][string]$Target,[AllowNull()][string]$ExpectedTarget)
 $prefix="$PublicIp/32"
 $old=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix $prefix -ErrorAction SilentlyContinue)
 if($old.Count -gt 1){throw 'Multiple matching routes exist. Review them before changing this target.'}
 $oldTarget=if($old.Count){[string]$old[0].NextHop}else{''}
 if($oldTarget -cne [string]$ExpectedTarget){throw 'The loopback target changed. Refresh and review it before applying.'}
 if([string]$Target -ceq $oldTarget){return}
 $persistent=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix $prefix -PolicyStore PersistentStore -ErrorAction SilentlyContinue)
 if(@($persistent | Where-Object {$_.NextHop -cne $oldTarget -or -not $old.Count -or $_.InterfaceIndex -ne $old[0].InterfaceIndex}).Count){throw 'A different persistent route exists. Review it before applying.'}
 $iface=0
 if($Target){
   if(@(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -eq $Target}).Count){throw 'The loopback target is an address on this Windows PC. Use router NAT loopback or a separate server address.'}
   $best=@(Find-NetRoute -RemoteIPAddress $Target -ErrorAction Stop)
   $local=@($best | Where-Object {$_.IPAddress})
   $direct=@($best | Where-Object {$_.DestinationPrefix -and $_.NextHop -eq '0.0.0.0'})
   if(-not $local.Count -or -not $direct.Count -or $local[0].IPAddress -eq $Target){throw 'Choose a separate server IP directly reachable from this Windows PC.'}
   $iface=[int]$direct[0].InterfaceIndex
 }
 $remove={
   foreach($store in @('PersistentStore','ActiveStore')){
     Get-NetRoute -AddressFamily IPv4 -DestinationPrefix $prefix -PolicyStore $store -ErrorAction SilentlyContinue |
       Where-Object {$_.NextHop -ceq $oldTarget -and $_.InterfaceIndex -eq $old[0].InterfaceIndex} |
       Remove-NetRoute -Confirm:$false -ErrorAction Stop
   }
 }
 try {
   if($old.Count){& $remove}
   if($Target){New-NetRoute -DestinationPrefix $prefix -InterfaceIndex $iface -NextHop $Target -RouteMetric 1 -ErrorAction Stop | Out-Null}
   $check=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix $prefix -ErrorAction SilentlyContinue)
   if(($Target -and ($check.Count -ne 1 -or $check[0].NextHop -cne $Target)) -or (-not $Target -and $check.Count)){throw 'Windows did not confirm the requested loopback target.'}
 } catch {
   $failure=$_
   if($Target){foreach($store in @('PersistentStore','ActiveStore')){Get-NetRoute -AddressFamily IPv4 -DestinationPrefix $prefix -PolicyStore $store -ErrorAction SilentlyContinue | Where-Object {$_.NextHop -ceq $Target -and $_.InterfaceIndex -eq $iface} | Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue}}
   if($old.Count -and -not @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix $prefix -ErrorAction SilentlyContinue).Count){
     $restore=@{DestinationPrefix=$prefix;InterfaceIndex=[int]$old[0].InterfaceIndex;NextHop=$oldTarget;RouteMetric=[int]$old[0].RouteMetric;ErrorAction='Stop'}
     if(-not $persistent.Count){$restore.PolicyStore='ActiveStore'}
     New-NetRoute @restore | Out-Null
   }
   throw $failure
 }
}
"""


def apply(windows_script,change):
    # All embedded values are strictly parsed literal IPv4s, never shell input.
    payload=base64.b64encode(json.dumps(change).encode()).decode()
    # Result location is generated by the unprivileged launcher and passed as a literal.
    child=ROUTE_FUNCTION+"\n$ErrorActionPreference='Stop';$resultPath=RESULT;try {$v=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"+payload+"'))|ConvertFrom-Json;Set-DstDockerLoopbackRoute -PublicIp $v.publicIp -Target $v.target -ExpectedTarget $v.expectedTarget;$r=@{ok=$true}}catch{$r=@{ok=$false;error=$_.Exception.Message}};[IO.File]::WriteAllText($resultPath,($r|ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))"
    encoded=base64.b64encode(child.encode('utf-8')).decode()
    launcher=r"""$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$folder=Join-Path $env:LOCALAPPDATA 'DSTDocker';[void][IO.Directory]::CreateDirectory($folder)
$result=Join-Path $folder ('loopback-'+[guid]::NewGuid().ToString('N')+'.json')
$script=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('CHILD')).Replace('RESULT',("'"+$result.Replace("'","''")+"'"))
$encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
try{
 $process=Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -Verb RunAs -WindowStyle Hidden -ArgumentList @('-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',$encoded) -PassThru
 if(-not $process.WaitForExit(120000)){throw 'Windows approval is still pending. Check the Windows permission prompt before retrying.'}
 if(-not (Test-Path -LiteralPath $result)){throw 'The loopback route was not changed. Windows approval may have been cancelled.'}
 Get-Content -LiteralPath $result -Raw
}finally{Remove-Item -LiteralPath $result -Force -ErrorAction SilentlyContinue}
""".replace('CHILD',encoded)
    result=json.loads(windows_script(launcher))
    if not result.get('ok'): raise ValueError(result.get('error','Windows did not apply the loopback target.'))


def operation(directory):
    path=directory/'loopback-operation.json'
    if not path.exists(): return None
    value=json.loads(path.read_text())
    return value
