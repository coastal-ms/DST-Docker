"""Narrow backup mirror job: owned backup volume to the configured host folder."""
import json,os,re
from pathlib import PurePosixPath
from engine import EngineError

def destination(engine):
    own=engine.inspect(os.environ['HOSTNAME'])
    compose=(own.get('Config',{}).get('Labels') or {}).get('com.docker.compose.project','')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}',compose):raise ValueError('The mirror installation identity is unavailable.')
    mounts=[row for row in own.get('Mounts',[]) if row.get('Destination')=='/mirror']
    if not mounts:return {'available':False,'composeProject':compose}
    if len(mounts)!=1 or mounts[0].get('Type')!='bind' or mounts[0].get('RW') is not True:raise ValueError('The host mirror folder mount needs review.')
    folder=mounts[0].get('Source','');path=PurePosixPath(folder)
    if not path.is_absolute() or '..' in path.parts or path in {PurePosixPath('/'),PurePosixPath('/root'),PurePosixPath('/home'),PurePosixPath('/tmp')}:
        raise ValueError('The configured mirror folder must be a dedicated host folder.')
    if any(path==PurePosixPath(root) or PurePosixPath(root) in path.parents for root in ('/etc','/proc','/sys','/dev','/usr','/bin','/sbin','/run','/var/lib/docker')):
        raise ValueError('System folders cannot be used for backup copies.')
    return {'available':True,'composeProject':compose,'folder':folder,'image':own['Image']}

def create(engine,project,request):
    if (not re.fullmatch(r'[a-f0-9]{32}',project) or not isinstance(request,dict) or
        not re.fullmatch(r'[a-f0-9]{32}',str(request.get('id',''))) or type(request.get('attempt')) is not int or not 0<=request['attempt']<=100 or
        not isinstance(request.get('files'),list) or not 1<=len(request['files'])<=100):raise ValueError('Choose a bounded backup mirror batch.')
    for row in request['files']:
        if (not isinstance(row,dict) or not re.fullmatch(r'backup-[0-9]+-[a-f0-9]{8}\.dump',str(row.get('name',''))) or
            not re.fullmatch(r'[a-f0-9]{64}',str(row.get('sha256',''))) or type(row.get('bytes')) is not int or row['bytes']<=0):
            raise ValueError('Mirror entries must be recorded native backups.')
    target=destination(engine)
    if not target['available']:raise ValueError('Prepare the host backup folder with the DST launcher first.')
    volume='dst-'+project+'-backups';labels=engine.request('GET','/volumes/'+volume).get('Labels') or {}
    if labels.get('io.dst.managed')!='true' or labels.get('io.dst.project')!=project:raise ValueError('Mirror source storage does not belong to this world.')
    payload=json.dumps({'id':request['id'],'attempt':request['attempt'],'project':project,'composeProject':target['composeProject'],'files':request['files']})
    name='dst-'+project+'-db-mirror-'+request['id']+'-'+str(request['attempt'])
    def existing():
        found=engine.request('GET','/containers/'+name+'/json',expected=(200,404))
        if not found or not found.get('Id'):return None
        engine.assert_owned(found['Id'],project,'db-mirror')
        host=found.get('HostConfig',{});config=found.get('Config',{});mounts=host.get('Mounts',[])
        if (config.get('Cmd')!=['-B','/opt/dst-manager/backup_mirror.py'] or config.get('Entrypoint')!=['python3'] or config.get('User')!='0:0' or
            'DST_BACKUP_MIRROR='+payload not in config.get('Env',[]) or host.get('NetworkMode')!='none' or len(mounts)!=2 or
            not any(row.get('Source')==volume and row.get('Target')=='/backups' and row.get('ReadOnly') is True for row in mounts) or
            not any(row.get('Type')=='bind' and row.get('Source')==target['folder'] and row.get('Target')=='/mirror' for row in mounts)):
            raise EngineError('The recorded mirror job does not match this installation.')
        return found['Id']
    found=existing()
    if found:return found
    try:return engine.request('POST','/containers/create?name='+name,{
        'Image':target['image'],'User':'0:0','Entrypoint':['python3'],'Cmd':['-B','/opt/dst-manager/backup_mirror.py'],
        'Env':['DST_BACKUP_MIRROR='+payload],
        'Labels':{'io.dst.managed':'true','io.dst.project':project,'io.dst.component':'db-mirror'},
        'HostConfig':{'NetworkMode':'none','CapDrop':['ALL'],'CapAdd':['CHOWN','DAC_OVERRIDE'],'SecurityOpt':['no-new-privileges:true'],
                      'Memory':128*1024**2,'MemorySwap':128*1024**2,'NanoCpus':1_000_000_000,'PidsLimit':16,
                      'Mounts':[{'Type':'volume','Source':volume,'Target':'/backups','ReadOnly':True},
                                {'Type':'bind','Source':target['folder'],'Target':'/mirror'}],
                      'RestartPolicy':{'Name':'no'},'LogConfig':{'Type':'json-file','Config':{'max-size':'1m','max-file':'2'}}}})['Id']
    except EngineError:
        found=existing()
        if found:return found
        raise
