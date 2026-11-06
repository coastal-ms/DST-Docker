import json
import socket
import sys

try:
    raw=sys.stdin.buffer.read(4*1024*1024+1)
    request=json.loads(raw)
    limit=4*1024*1024 if request.get('action') in {'settings.write','settings.startup'} else 65536
    if len(raw)>limit: raise ValueError()
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
        connection.settimeout(40)
        connection.connect('/control/manager.sock')
        connection.sendall(raw+b'\n')
        with connection.makefile('rb') as stream: response=stream.readline(8*1024*1024+1)
    if len(response)>8*1024*1024:raise ValueError()
    sys.stdout.buffer.write(response)
except Exception:
    print(json.dumps({'ok':False,'error':'Docker management service is unavailable.'}))
