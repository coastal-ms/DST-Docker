"""Owner-requested portal HTTPS setup; the host retains all private keys."""
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import threading
import time
import uuid
from urllib.parse import urlsplit


def atomic(path, value):
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temporary.open('x',encoding='utf-8') as stream:
        os.chmod(temporary,0o600);json.dump(value,stream)
    temporary.replace(path)


class HttpsControl:
    def __init__(self, root, source, compose):
        self.root=Path(root);self.source=source;self.compose=compose
        self.path=self.root/'portal-update/https-operation.json'
        self.operation=json.loads(self.path.read_text()) if self.path.exists() else None
        self.certificate_cache=None
        if self.operation and self.operation.get('phase')=='running':
            self.record(phase='failed',message='HTTPS setup was interrupted. Review the connection and retry.')

    def record(self, **patch):
        self.operation={**(self.operation or {}),**patch}
        atomic(self.path,self.operation)

    def tls(self):
        spec=importlib.util.spec_from_file_location('dst_portal_https',self.source()/'packaging/docker/https.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def project(self):
        name=json.loads(self.compose('config','--format','json'))['name']
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}',name):raise ValueError('Invalid installation identity.')
        return name

    def addresses(self):
        raw=subprocess.check_output(['ip','-j','-4','address','show'],timeout=10)
        return sorted({str(ipaddress.IPv4Address(row['local'])) for interface in json.loads(raw)
                       for row in interface.get('addr_info',[]) if not interface.get('ifname','').startswith(('lo','docker','br-','veth')) and row.get('family')=='inet'
                       and not ipaddress.IPv4Address(row['local']).is_loopback})

    def configuration(self):
        for name in ('https.compose.json','https.pending.compose.json','https.saved.compose.json'):
            path=self.root/name
            if path.is_file():return path,json.loads(path.read_text())
        previous=sorted(self.root.glob('https.compose.json.disabled.*'),key=lambda p:p.stat().st_mtime,reverse=True)
        if previous:return previous[0],json.loads(previous[0].read_text())
        return None,None

    def certificate(self):
        tls=self.tls()
        pem=tls.public_root(self.project())
        der=ssl.PEM_cert_to_DER_cert(pem)
        fingerprint=hashlib.sha256(der).hexdigest()
        self.certificate_cache={'pem':pem,'sha256':fingerprint}
        return self.certificate_cache.copy()

    def status(self, port):
        path,value=self.configuration()
        active=(self.root/'https.compose.json').is_file()
        origin=value.get('x-dst-https-origin','') if value else ''
        parsed=urlsplit(origin)
        if origin and (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password):
            raise ValueError('The HTTPS configuration needs recovery.')
        if value and not self.certificate_cache:
            try:self.certificate()
            except (ValueError,RuntimeError):pass
        certificate=self.certificate_cache or {}
        return {'supported':True,'enabled':active,'prepared':bool(value and certificate),
                'url':origin,'address':parsed.hostname or '', 'port':parsed.port or port,
                'addresses':self.addresses(),'sha256':certificate.get('sha256'),
                'certificateAvailable':bool(certificate),'operation':self.operation,
                'clientTrustInstalled':False}

    def start(self, request):
        action=request.get('action');port=request.get('port')
        if type(port) is not int or not 1024<=port<=65535:raise ValueError('Invalid console port.')
        if action=='https.prepare':
            if set(request)!={'action','address','port'}:raise ValueError('Choose the host address.')
            try:address=str(ipaddress.IPv4Address(request['address']))
            except (ValueError,TypeError):raise ValueError('Choose an IPv4 address of this host.')
            if address not in self.addresses():raise ValueError('Choose an address currently assigned to this host.')
            if (self.root/'https.compose.json').exists():raise ValueError('HTTPS is already enabled. Turn it off before changing its address.')
            selected={'action':action,'address':address,'port':port}
        elif action=='https.enable':
            if set(request)!={'action','sha256','port'}:raise ValueError('Confirm the prepared certificate.')
            pending=self.root/'https.pending.compose.json'
            if not pending.is_file():raise ValueError('Prepare HTTPS and trust its certificate first.')
            fingerprint=self.certificate()['sha256']
            if request['sha256']!=fingerprint:raise ValueError('The certificate changed. Download and verify it again.')
            value=json.loads(pending.read_text());parsed=urlsplit(value['x-dst-https-origin'])
            if parsed.port!=port or parsed.hostname not in self.addresses():raise ValueError('The console address changed. Prepare HTTPS again.')
            selected={'action':action,'address':parsed.hostname,'port':port,'sha256':fingerprint}
        elif action=='https.disable':
            if set(request)!={'action','port'}:raise ValueError('Choose the HTTPS action.')
            if not (self.root/'https.compose.json').is_file():raise ValueError('HTTPS is not enabled.')
            selected={'action':action,'port':port}
        else:raise ValueError('Choose a supported HTTPS action.')
        self.record(id=uuid.uuid4().hex,phase='running',action=action,message='Preparing HTTPS.' if action=='https.prepare' else 'Changing the portal connection. Game maps keep running.',startedAt=time.time())
        threading.Thread(target=self.worker,args=(selected,),daemon=True).start()
        return self.status(port)

    def prepare(self, selected):
        import argparse
        tls=self.tls();project=self.project();pending=self.root/'https.pending.compose.json'
        previous,value=self.configuration()
        if previous and previous!=pending:atomic(pending,value)
        internal=value.get('x-dst-http-internal-port') if value else None
        if not internal or internal==selected['port']:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0));internal=probe.getsockname()[1]
        args=argparse.Namespace(project=project,address=selected['address'],port=selected['port'],
                                upstream_port=internal,output=str(pending),app_image='dst-docker:local')
        (tls.update if pending.exists() else tls.prepare)(args)
        tls.initialize_root(project)
        self.certificate()

    def launch(self, *args):
        # Only fixed launcher actions and validated address/port values reach here.
        result=subprocess.run(['sh',str(self.source()/'bin/dst-docker'),*args],cwd=self.source(),
                              stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=300)
        if result.returncode:raise ValueError('The portal connection could not be changed. Check the hosting window and retry.')

    def reconcile_tailscale(self, port):
        raw=self.compose('exec','-T','dst','python3','/opt/dst/packaging/docker/manager-client.py',
                         input=json.dumps({'action':'tailscale.get','port':port}).encode())
        if not json.loads(raw).get('ok'):raise ValueError('Reconnect Tailscale in Settings after changing this connection.')

    def worker(self, selected):
        active=self.root/'https.compose.json';pending=self.root/'https.pending.compose.json'
        try:
            if selected['action']=='https.prepare':self.prepare(selected)
            elif selected['action']=='https.enable':
                # Preparation leaves HTTP untouched; only this explicit second step switches it.
                atomic(active,json.loads(pending.read_text()))
                try:
                    self.launch('https',selected['address'],str(selected['port']))
                    self.reconcile_tailscale(json.loads(active.read_text())['x-dst-http-internal-port'])
                except Exception:
                    try:
                        self.launch('http',str(selected['port']))
                        self.reconcile_tailscale(selected['port'])
                    except Exception:pass
                    raise
            else:
                atomic(self.root/'https.saved.compose.json',json.loads(active.read_text()))
                self.launch('http',str(selected['port']))
                self.reconcile_tailscale(selected['port'])
            self.record(phase='completed',message='HTTPS is prepared. Download and trust its certificate before enabling it.' if selected['action']=='https.prepare' else 'The portal connection was updated.',finishedAt=time.time())
        except Exception:
            self.record(phase='failed',message='HTTPS setup did not finish. Existing certificates and world data were kept. Review the connection, then retry; the hosting window can restore HTTP.',finishedAt=time.time())
