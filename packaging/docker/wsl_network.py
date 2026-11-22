"""Read-only Windows/WSL addresses for router forwarding guidance."""
import ipaddress
import json
import socket
import subprocess


def local_address():
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as connection:
        connection.connect(('1.1.1.1',53))
        return connection.getsockname()[0]


def snapshot(windows_script,run,public_ip=None):
    if public_ip:
        parsed=ipaddress.IPv4Address(public_ip)
        if not parsed.is_global or parsed.is_multicast:raise ValueError('Choose a public IPv4 address for loopback status.')
    script=("$ErrorActionPreference='Stop';$candidate=$null;"
            "$routes=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric);"
            "foreach($route in $routes){"
            "$candidate=Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex | "
            "Where-Object {$_.AddressState -eq 'Preferred' -and -not $_.SkipAsSource -and $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -notlike '127.*'} | Select-Object -First 1;"
            "if($candidate){break}};"
            "if(-not $candidate){throw 'No Windows LAN address found.'};"
            "@{dockerIp=$candidate.IPAddress;LOOPBACK}|ConvertTo-Json -Compress")
    loopback="loopbackTarget=$null"
    if public_ip:
        loopback="loopbackTarget=(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '"+str(parsed)+"/32' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1 -ExpandProperty NextHop)"
    script=script.replace('LOOPBACK',loopback)
    value=json.loads(windows_script(script))
    address=ipaddress.IPv4Address(value['dockerIp'])
    if address.is_loopback or address.is_unspecified or address.is_multicast or address.is_link_local:
        raise ValueError('The Windows LAN address is unavailable.')
    try:
        mode=run(['wslinfo','--networking-mode']).stdout.decode().strip().lower()
    except (OSError,subprocess.SubprocessError):mode='unknown'
    if mode not in {'nat','mirrored','bridged','virtioproxy','none'}:mode='unknown'
    linux_ip=local_address()
    return {'dockerIp':linux_ip if mode in {'nat','bridged'} else str(address),'windowsIp':str(address),'wslIp':linux_ip,'networkingMode':mode,'routerForwardIp':linux_ip if mode=='bridged' else str(address),'loopbackTarget':value.get('loopbackTarget')}
