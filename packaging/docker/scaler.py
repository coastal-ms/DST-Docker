"""Authenticated internal director-to-Docker map scaling adapter."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import socket
import ssl
import signal
from urllib.parse import urlsplit

TOKEN=Path('/etc/dst-scaler/token').read_text().strip()
WORLD=Path('/etc/dst-scaler/world').read_text().strip()
BASE='/apis/igw.funcom.com/v1/namespaces/'+WORLD+'/'


def manager(request):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
        connection.settimeout(30);connection.connect('/control/manager.sock')
        connection.sendall(json.dumps(request).encode()+b'\n')
        with connection.makefile('rb') as stream:raw=stream.readline(2*1024*1024)
        response=json.loads(raw)
        if not response.get('ok'):raise ValueError(response.get('error','Map orchestration is unavailable.'))
        return response['data']


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,status,value):
        body=json.dumps(value).encode();self.send_response(status)
        self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
    def authorized(self):
        if not hmac.compare_digest(self.headers.get('Authorization','').encode(),'Bearer '.encode()+TOKEN.encode()):
            self.reply(401,{'kind':'Status','status':'Failure','reason':'Unauthorized','code':401});return False
        return True
    def do_GET(self):
        if not self.authorized():return
        path=urlsplit(self.path).path
        try:
            state=manager({'action':'scale.get'})
            if path==BASE+'battlegroups/'+WORLD:value=state['battlegroup']
            elif path==BASE+'serversetscales':value={'apiVersion':'igw.funcom.com/v1','kind':'ServerSetScaleList','metadata':{},'items':state['scales']}
            elif path.startswith(BASE+'serversetscales/'):
                name=path[len(BASE+'serversetscales/'):]
                value=next((row for row in state['scales'] if row['metadata']['name']==name),None)
                if value is None:self.reply(404,{'kind':'Status','reason':'NotFound','code':404});return
            else:self.reply(404,{'kind':'Status','reason':'NotFound','code':404});return
            self.reply(200,value)
        except Exception:self.reply(503,{'kind':'Status','reason':'ServiceUnavailable','code':503})
    def do_PATCH(self):
        if not self.authorized():return
        path=urlsplit(self.path).path
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=65536:raise ValueError('Invalid orchestration request size.')
            patch=json.loads(self.rfile.read(size))
            if path==BASE+'battlegroupdirectorstats/'+WORLD:
                # Telemetry is not an instruction source and is not logged.
                self.reply(200,{'apiVersion':'igw.funcom.com/v1','kind':'BattleGroupDirectorStats','metadata':{'name':WORLD},'spec':{}});return
            if not path.startswith(BASE+'serversetscales/'):
                self.reply(404,{'kind':'Status','reason':'NotFound','code':404});return
            if self.headers.get('Content-Type','').split(';',1)[0]!='application/json-patch+json':raise ValueError('Unsupported patch encoding.')
            result=manager({'action':'scale.patch','name':path[len(BASE+'serversetscales/'):],'patch':patch})
            self.reply(200,result)
        except ValueError:self.reply(409,{'kind':'Status','reason':'Conflict','code':409})
        except Exception:self.reply(503,{'kind':'Status','reason':'ServiceUnavailable','code':503})


if __name__=='__main__':
    server=ThreadingHTTPServer(('0.0.0.0',8443),Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain('/etc/dst-scaler/cert.pem','/etc/dst-scaler/key.pem')
    server.socket=context.wrap_socket(server.socket,server_side=True)
    def shutdown(*_):raise SystemExit(0)
    signal.signal(signal.SIGTERM,shutdown)
    try:server.serve_forever()
    finally:server.server_close()
