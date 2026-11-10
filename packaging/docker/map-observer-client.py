"""Transport bundled Atlas observations to the matching isolated PID reader."""
import base64
import json
from pathlib import Path
import socket
import sys


if __name__=='__main__':
    request=json.load(sys.stdin)
    folder=Path(request['commandFile']).resolve().parent
    allowed=Path('/data/state/DuneServer/atlas/runtimes').resolve()
    if not folder.is_relative_to(allowed):raise ValueError('Observer source is outside the packaged runtime.')
    partition='1' if folder.name=='hagga' else '8'
    body={'command':Path(request['commandFile']).read_text().replace('\r',''),
          'timeout':min(300,max(1,int(request['timeout']))),
          'input':base64.b64encode(Path(request['inputFile']).read_bytes()).decode() if request.get('inputFile') else ''}
    targets=[Path('/map-control/game-'+partition+'.sock')]
    setup=Path(request['commandFile']).name.startswith('reader-setup-')
    if setup:
        # Atlas shares its helper setup between the two worlds. Each isolated
        # PID reader needs its own copy of the same verified O_RDONLY tools.
        targets=[path for path in [Path('/map-control/game-1.sock'),Path('/map-control/game-8.sock')] if path.exists()]
        if not targets:raise RuntimeError('No native map reader is running.')
    completed=0
    for target in targets:
        connection=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);connection.settimeout(body['timeout']+5)
        try:
            try:connection.connect(str(target))
            except (FileNotFoundError,ConnectionRefusedError):
                if setup:continue
                raise
            connection.sendall(json.dumps(body).encode()+b'\n')
            with connection.makefile('rb') as stream:raw=stream.readline(48*1024*1024)
            reply=json.loads(raw)
            if not reply['ok']:
                sys.stderr.buffer.write(base64.b64decode(reply.get('error','')))
                sys.exit(reply.get('exitCode',1) or 1)
            Path(request['outputFile']).write_bytes(base64.b64decode(reply['output']))
            completed+=1
        finally:connection.close()
    if not completed:raise RuntimeError('No native map reader is available.')
