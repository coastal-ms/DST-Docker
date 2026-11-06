import json
import socket
import sys

MAX_WIRE=4*1024*1024


def request(payload):
    raw=json.dumps(payload,ensure_ascii=False).encode('utf-8')
    if len(raw)>MAX_WIRE:raise ValueError('Settings request exceeds its limit.')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
        connection.settimeout(15)
        connection.connect('/map-control/settings/settings.sock')
        connection.sendall(raw+b'\n')
        with connection.makefile('rb') as stream:response=stream.readline(MAX_WIRE+1)
    if len(response)>MAX_WIRE:raise ValueError('Settings response exceeds its limit.')
    return json.loads(response)


if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(MAX_WIRE+1)
        if len(raw)>MAX_WIRE:raise ValueError('Settings request exceeds its limit.')
        result=request(json.loads(raw))
    except Exception:result={'ok':False,'error':'The server settings service is unavailable.'}
    sys.stdout.write(json.dumps(result,ensure_ascii=False))
