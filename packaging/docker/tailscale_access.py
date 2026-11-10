"""Optional, installation-owned userspace Tailscale proxy. Never touches maps."""
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import quote
from engine import EngineConnection, EngineError

IMAGE='tailscale/tailscale@sha256:ed6480b33c6eb67c9cbd203ed42b9fb57e361986725b6856def71b7a3d9e276c'
LOCK=threading.RLock()
WORKER=None


def read(path):
    try:return json.loads(path.read_text())
    except FileNotFoundError:return {'mode':'off','phase':'off'}


def write(path,value,shared=False):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value),encoding='utf-8')
    temporary.chmod(0o640 if shared else 0o600)
    if shared:os.chown(temporary,-1,10001)
    temporary.replace(path)


def public(value):
    return {key:value[key] for key in ('mode','phase','url','loginUrl','message') if key in value}


def owned(engine,project):
    row=engine.request('GET','/containers/dst-'+project+'-tailscale/json',expected=(200,404))
    if row:engine.assert_owned(row['Id'],project,'tailscale')
    return row


def ensure_image(engine):
    if engine.request('GET','/images/'+quote(IMAGE,safe='')+'/json',expected=(200,404)):return
    connection=EngineConnection();connection.timeout=180
    try:
        connection.request('POST','/images/create?fromImage='+quote(IMAGE,safe=''))
        response=connection.getresponse()
        if response.status!=200:raise EngineError('Tailscale could not be downloaded. Retry Connect.')
        # Stream the registry response; neither credentials nor daemon output leave this helper.
        while True:
            line=response.readline(65537)
            if not line:break
            if len(line)>65536 or json.loads(line).get('error'):raise EngineError('Tailscale download failed. Retry Connect.')
    finally:connection.close()
    engine.request('GET','/images/'+quote(IMAGE,safe='')+'/json')


def ensure_container(engine,project):
    row=owned(engine,project)
    if row:
        if row['State']['Status']!='running':engine.lifecycle(row['Id'],project,'start')
        return row['Id']
    ensure_image(engine)
    volume='dst-'+project+'-tailscale-state'
    labels={'io.dst.managed':'true','io.dst.project':project,'io.dst.component':'tailscale'}
    existing=engine.request('GET','/volumes/'+volume,expected=(200,404))
    if existing:
        if any(existing.get('Labels',{}).get(key)!=value for key,value in labels.items()):raise ValueError('Tailscale storage belongs to another installation.')
    else:engine.request('POST','/volumes/create',{'Name':volume,'Labels':labels})
    identifier=engine.request('POST','/containers/create?name=dst-'+project+'-tailscale',{
        'Image':IMAGE,'Entrypoint':['tailscaled'],'Cmd':['--tun=userspace-networking','--state=/var/lib/tailscale/tailscaled.state','--socket=/tmp/tailscaled.sock'],
        'Labels':labels,
        'HostConfig':{'NetworkMode':'host','ReadonlyRootfs':True,'CapDrop':['ALL'],'SecurityOpt':['no-new-privileges:true'],
            'RestartPolicy':{'Name':'unless-stopped'},'Memory':256*1024**2,'PidsLimit':128,
            'Tmpfs':{'/tmp':'rw,nosuid,size=32m'},'Mounts':[{'Type':'volume','Source':volume,'Target':'/var/lib/tailscale'}],
            'LogConfig':{'Type':'json-file','Config':{'max-size':'2m','max-file':'2'}}}})['Id']
    engine.lifecycle(identifier,project,'start')
    return identifier


def cli(engine,identifier,project,args):
    return engine.exec_internal(identifier,project,'tailscale',['tailscale','--socket=/tmp/tailscaled.sock',*args])


def command_output(engine,identifier,project,args):
    # These arguments are all internal constants/validated numbers, never user commands.
    import shlex
    command=shlex.join(['timeout','8s','tailscale','--socket=/tmp/tailscaled.sock',*args])
    return engine.exec_internal(identifier,project,'tailscale',['sh','-c',command+' 2>&1; exit 0'])


def login_url(output):
    match=re.search(r'https://login\.tailscale\.com/[A-Za-z0-9_./?=&%:+-]+',output)
    return match.group(0) if match else ''


def connected_url(status):
    name=(status.get('Self') or {}).get('DNSName','').rstrip('.')
    return 'https://'+name if re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+\.ts\.net',name) else ''


def change(engine,project,path,origin,mode,port):
    value={'mode':mode,'phase':'connecting','message':'Preparing Tailscale…','port':port}
    def update(**changes):
        value.update(changes)
        with LOCK:write(path,value)
    try:
        row=owned(engine,project)
        if mode=='off':
            # Revoke the published origin immediately, including on a stop failure.
            origin.unlink(missing_ok=True)
            if row and row['State']['Status']=='running':engine.lifecycle(row['Id'],project,'stop')
            update(phase='off',message='Remote access is off. The saved Tailscale connection is retained.')
            return
        identifier=ensure_container(engine,project)
        for attempt in range(20):
            try:status=json.loads(cli(engine,identifier,project,['status','--json']));break
            except (EngineError,ValueError):time.sleep(.25)
        else:raise ValueError('Tailscale has not started yet. Retry Connect.')
        if status.get('BackendState')!='Running':
            output=command_output(engine,identifier,project,['up','--accept-dns=false','--hostname=dst-console-'+project[:8],'--timeout=3s'])
            status=json.loads(cli(engine,identifier,project,['status','--json']))
            if status.get('BackendState')!='Running':
                url=login_url(output) or login_url(status.get('AuthURL',''))
                update(phase='login-required',loginUrl=url,message='Sign in to Tailscale to connect this Docker installation.' if url else 'Tailscale sign-in is not ready. Retry Connect.')
                return
        url=connected_url(status)
        if not url:raise ValueError('Enable MagicDNS in Tailscale, then retry Connect.')
        # Reset the owned node's previous mode so Funnel cannot survive a switch to private.
        cli(engine,identifier,project,['serve','reset'])
        output=command_output(engine,identifier,project,['funnel' if mode=='public' else 'serve','--bg','--yes','--https=443','http://127.0.0.1:'+str(port)])
        config=json.loads(cli(engine,identifier,project,['serve','status','--json']))
        handlers=config.get('Web',{}).get(url.removeprefix('https://')+':443',{}).get('Handlers',{})
        allowed=config.get('AllowFunnel',{}).get(url.removeprefix('https://')+':443',False)
        if handlers.get('/',{}).get('Proxy')!='http://127.0.0.1:'+str(port) or bool(allowed)!=(mode=='public'):
            origin.unlink(missing_ok=True)
            update(phase='setup-required',loginUrl=login_url(output),message='Complete HTTPS or Funnel setup in Tailscale, then retry Connect.')
            return
        write(origin,{'origin':url,'mode':mode},shared=True)
        update(phase='connected',url=url,message='Public HTTPS access is connected.' if mode=='public' else 'Private Tailscale access is connected.')
    except Exception as error:
        origin.unlink(missing_ok=True)
        update(phase='failed',message=str(error) if isinstance(error,ValueError) else 'Tailscale could not connect. Retry Connect; game maps were not changed.')


def request(engine,project,directory,config,action,mode=None,port=8088):
    global WORKER
    if not re.fullmatch(r'[a-f0-9]{32}',project):raise ValueError('Invalid installation.')
    path=Path(directory)/'tailscale.json';origin=Path(config)/'docker-tailscale-origin.json'
    with LOCK:
        value=read(path)
        busy=bool(WORKER and WORKER.is_alive())
        if action=='link':
            # A read-only map viewer receives no enrollment URL or node details.
            return {'url':value.get('url','') if value.get('phase')=='connected' else '', 'mode':value.get('mode','off')}
        if action=='get' and not busy and value.get('phase') in {'login-required','connected'}:
            row=owned(engine,project)
            if row and row['State']['Status']=='running':
                try:status=json.loads(cli(engine,row['Id'],project,['status','--json']))
                except (EngineError,ValueError):status={}
                if status.get('BackendState')=='Running' and (value['phase']=='login-required' or value.get('port')!=port):mode=value['mode'];action='set'
                elif status.get('BackendState')!='Running' and value['phase']=='connected':
                    origin.unlink(missing_ok=True)
                    value.update(phase='login-required',url='',loginUrl=login_url(status.get('AuthURL','')),message='Reconnect this installation to Tailscale.');write(path,value)
            elif value.get('phase')=='connected':
                origin.unlink(missing_ok=True)
                value.update(phase='offline',url='',message='Tailscale is stopped. Select Connect to resume.');write(path,value)
        if action=='get':return {**public(value),'busy':busy}
        if action!='set' or mode not in {'off','private','public'}:raise ValueError('Choose Off, Private or Public HTTPS access.')
        if type(port) is not int or not 1024<=port<=65535:raise ValueError('The Docker console listener port is invalid.')
        if busy:return {**public(value),'busy':True}
        value={'mode':mode,'phase':'connecting','message':'Preparing Tailscale…','port':port};write(path,value)
        WORKER=threading.Thread(target=change,args=(engine,project,path,origin,mode,port),daemon=True,name='DuneTailscale')
        WORKER.start()
        return {**public(value),'busy':True}


def resume(engine,project,directory,config):
    value=read(Path(directory)/'tailscale.json')
    if value.get('mode') in {'private','public'}:
        request(engine,project,directory,config,'set',value['mode'],value.get('port',8088))
