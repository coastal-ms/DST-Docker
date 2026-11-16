"""Fixed-action client for the installed product updater."""
import json
import socket
import sys

try:
    raw = sys.stdin.buffer.read(4097)
    if len(raw) > 4096: raise ValueError()
    request = json.loads(raw)
    if request.get('action') not in {'status', 'install'}: raise ValueError()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(40); connection.connect('/update-control/update.sock')
        connection.sendall(raw + b'\n')
        with connection.makefile('rb') as stream: response = stream.readline(65537)
        if len(response) > 65536: raise ValueError()
    sys.stdout.buffer.write(response)
except (FileNotFoundError, ConnectionRefusedError):
    print(json.dumps({'ok': True, 'data': {'supported': False, 'available': False,
          'error': 'Rerun the installation command once with the same path to enable browser updates. The host needs systemd and GitHub access.'}}))
except Exception:
    print(json.dumps({'ok': True, 'data': {'supported': True, 'available': False,
          'error': 'The DST update service did not respond. Check again; an update may still be running.'}}))
