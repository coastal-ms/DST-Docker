"""Private Atlas transport inside exactly one owned game PID namespace.

No network or Docker socket. Only the packaged portal observer can access the
Unix socket; browser resources cannot submit commands to this transport.
"""
import base64
import json
import os
from pathlib import Path
import resource
import signal
import socket
import socketserver
import struct
import subprocess
import tempfile
import threading

LIMIT=32*1024*1024
SLOTS=threading.BoundedSemaphore(2)


def limits():
    resource.setrlimit(resource.RLIMIT_FSIZE,(LIMIT,LIMIT))


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(310)
        try:
            _,uid,_=struct.unpack('3i',self.connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            if uid not in {0,10001}:raise ValueError('Observer identity rejected.')
            raw=self.rfile.readline(LIMIT+1)
            if len(raw)>LIMIT:raise ValueError('Observer input exceeds its limit.')
            request=json.loads(raw);command=request['command'];timeout=request.get('timeout',25)
            if not isinstance(command,str) or len(command)>131072 or type(timeout) is not int or not 1<=timeout<=300:
                raise ValueError('Invalid observer request.')
            source=base64.b64decode(request.get('input',''),validate=True)
            with SLOTS,tempfile.TemporaryFile() as output,tempfile.TemporaryFile() as errors:
                result=subprocess.Popen(['/bin/bash','-c',command],stdin=subprocess.PIPE,stdout=output,stderr=errors,
                    preexec_fn=limits,start_new_session=True)
                try:result.communicate(source,timeout=timeout)
                except BaseException:
                    try:os.killpg(result.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    result.wait()
                    raise
                output.seek(0);errors.seek(0)
                response={'ok':result.returncode==0,'exitCode':result.returncode,
                    'output':base64.b64encode(output.read(LIMIT)).decode(),
                    'error':base64.b64encode(errors.read(65536)).decode()}
        except Exception:
            response={'ok':False,'exitCode':1,'error':base64.b64encode(b'Native map observation failed.').decode()}
        self.wfile.write(json.dumps(response).encode()+b'\n')


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads=True


if __name__=='__main__':
    partition=os.environ['DST_MAP_PARTITION']
    if partition not in {'1','8'}:raise ValueError('Unsupported map observation partition.')
    os.umask(0o007);path=Path('/control/game-'+partition+'.sock')
    path.unlink(missing_ok=True)
    server=Server(str(path),Handler);os.chown(path,-1,10001);path.chmod(0o660)
    def shutdown(*_):raise SystemExit(0)
    signal.signal(signal.SIGTERM,shutdown)
    try:server.serve_forever()
    finally:
        server.server_close();path.unlink(missing_ok=True)
