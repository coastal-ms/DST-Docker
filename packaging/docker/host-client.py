"""Fixed-action client for the optional installed WSL host session."""
import json
import socket
import sys
try:
    request=json.loads(sys.stdin.buffer.read(4097))
    if request.get('action') not in {'status','shortcut','shutdown'}:raise ValueError()
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
        connection.settimeout(15);connection.connect('/host-control/host.sock')
        connection.sendall(json.dumps(request).encode()+b'\n')
        with connection.makefile('rb') as stream:response=stream.readline(65537)
    if len(response)>65536:raise ValueError()
    sys.stdout.buffer.write(response)
except Exception:
    print(json.dumps({'ok':False,'error':'Start DST using its desktop icon to enable WSL host controls.'}))
