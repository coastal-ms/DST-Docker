"""Docker Engine operations scoped to a single DST-owned project."""
import http.client
import json
import re
import socket
import struct
import io
import tarfile
import secrets
import time
import hashlib
import os
from urllib.parse import quote
from pathlib import Path


class EngineError(RuntimeError): pass


class EngineConnection(http.client.HTTPConnection):
    def __init__(self): super().__init__('localhost', timeout=30)
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/var/run/docker.sock')


class Engine:
    def create_asset_activation_job(self,project,operation,stage,build,mode,assets_volume):
        if any(not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{32}',value) for value in (project,operation,stage)) or not isinstance(build,str) or not re.fullmatch(r'[0-9]{1,18}',build) or mode not in {'activate','rollback'}:
            raise ValueError('Invalid package activation job.')
        labels=self.request('GET','/volumes/'+quote(assets_volume,safe='')).get('Labels',{})
        if labels.get('io.dst.managed')!='true' or labels.get('io.dst.component')!='official-assets':
            raise ValueError('Official package storage is not owned.')
        image=self.request('GET','/images/dst-docker-manager%3Alocal/json')
        if image.get('Config',{}).get('Labels',{}).get('io.dst.asset-activator')!='true':
            raise ValueError('Build the packaged activation helper first.')
        return self.request('POST','/containers/create?name=dst-'+project+'-asset-'+mode+'-'+operation[:16],{
            'Image':image['Id'],'User':'10001:10001','Entrypoint':['python3','-B','/opt/dst-manager/asset_activation.py'],
            'Env':['DST_PACKAGE_STAGE='+stage,'DST_PACKAGE_BUILD='+build,'DST_PACKAGE_MODE='+mode],
            'Labels':{'io.dst.managed':'true','io.dst.project':project,'io.dst.component':'asset-switch','io.dst.operation':operation,'io.dst.stage':stage},
            'HostConfig':{'NetworkMode':'none','ReadonlyRootfs':True,'Init':True,'CapDrop':['ALL'],'SecurityOpt':['no-new-privileges:true'],
                          'RestartPolicy':{'Name':'no'},'Memory':512*1024**2,'MemorySwap':512*1024**2,'NanoCpus':2_000_000_000,'PidsLimit':32,
                          'Mounts':[{'Type':'volume','Source':assets_volume,'Target':'/srv/dst'}],
                          'LogConfig':{'Type':'json-file','Config':{'max-size':'2m','max-file':'2'}}}})['Id']

    def set_component_memory(self, identifier, project, component, amount, swap_policy=None):
        if not re.fullmatch(r'game-[0-9]+',component) or type(amount) is not int or not 256*1024**2<=amount<=128*1024**3:
            raise ValueError('Invalid map memory allocation.')
        observed=self.assert_owned(identifier,project,component)
        if observed['State']['Status']=='running' and amount<observed['HostConfig']['Memory']:
            raise ValueError('Stop the map before reducing its memory allocation.')
        import memory_swap
        total=memory_swap.total_limit(amount,swap_policy)
        self.request('POST','/containers/'+identifier+'/update',{'Memory':amount,'MemorySwap':total})
        observed=self.assert_owned(identifier,project,component)
        if observed['HostConfig']['Memory']!=amount or observed['HostConfig']['MemorySwap']!=total:
            raise EngineError('The Docker map memory allocation could not be verified.')

    def set_component_swap(self, identifier, project, component, policy):
        import memory_swap
        if not re.fullmatch(r'game-[1-9][0-9]*',component):raise ValueError('Only owned game maps have Memory Swap allowances.')
        observed=self.assert_owned(identifier,project,component)
        memory=observed['HostConfig']['Memory'];total=memory_swap.total_limit(memory,policy)
        self.request('POST','/containers/'+identifier+'/update',{'MemorySwap':total})
        result=self.assert_owned(identifier,project,component)
        if result['HostConfig']['Memory']!=memory or result['HostConfig']['MemorySwap']!=total:
            raise EngineError('The game swap allowance could not be verified; its RAM was not changed.')

    def create_host_swap_job(self, project, request):
        import memory_swap
        if not re.fullmatch('[a-f0-9]{32}',project):raise ValueError('Invalid host swap ownership.')
        read_only=request.get('action')=='status'
        if not read_only:
            policy=memory_swap.validate(request)
            self.assert_swap_supported()
            request={**policy,'action':'configure','confirmation':request['confirmation']}
        else:request={'action':'status'}
        own=self.inspect(os.environ['HOSTNAME'])
        name='dst-'+project+'-host-swap-'+secrets.token_hex(8)
        return self.request('POST','/containers/create?name='+name,{
            'Image':own['Image'],'User':'0:0','Entrypoint':['python3','/opt/dst-manager/host_memory_swap.py'],
            'Cmd':[json.dumps({**request,'project':project})],
            'Labels':{'io.dst.managed':'true','io.dst.project':project,'io.dst.component':'host-memory-swap'},
            'HostConfig':{'NetworkMode':'none','Privileged':not read_only,'ReadonlyRootfs':False,
                          'RestartPolicy':{'Name':'no'},'Memory':128*1024**2,'MemorySwap':128*1024**2,
                          'PidsLimit':32,'SecurityOpt':['no-new-privileges:true'],
                          'Mounts':[{'Type':'bind','Source':'/','Target':'/host','ReadOnly':read_only}],
                          'LogConfig':{'Type':'json-file','Config':{'max-size':'1m','max-file':'1'}}}})['Id']

    def assert_swap_supported(self):
        info=self.request('GET','/info')
        if not info.get('SwapLimit') or any('rootless' in value for value in info.get('SecurityOptions',[])):
            raise ValueError('This Docker host cannot manage swap limits. Use a rootful Linux Docker Engine with swap accounting.')

    def set_component_cpu(self, identifier, project, component, cpus):
        if not re.fullmatch(r'game-[0-9]+', component) or (cpus is not None and (type(cpus) not in (int,float) or not .25 <= cpus <= 1024)):
            raise ValueError('Invalid map CPU allocation.')
        observed=self.assert_owned(identifier, project, component)
        # Docker treats NanoCpus=0 as "unchanged", so that API cannot clear a
        # saved cap. Use the reversible CFS quota API for optional DST caps.
        if observed.get('HostConfig',{}).get('NanoCpus',0):
            raise EngineError('This map has a legacy CPU cap. Refresh its stopped adapter before changing CPU limits.')
        quota = -1 if cpus is None else int(cpus * 100_000)
        self.request('POST', '/containers/' + identifier + '/update', {'CpuPeriod':100_000,'CpuQuota':quota})
        actual=self.assert_owned(identifier, project, component)['HostConfig']
        if actual.get('CpuQuota')!=quota or actual.get('CpuPeriod')!=100_000 or actual.get('NanoCpus',0):
            raise EngineError('The Docker map CPU allocation could not be verified.')

    def create_asset_stage_job(self, project, operation, build, assets_volume):
        if not re.fullmatch(r'[a-f0-9]{32}', project) or not re.fullmatch(r'[a-f0-9]{32}', operation) or not re.fullmatch(r'[0-9]{1,18}', build):
            raise ValueError('Invalid official update stage.')
        labels = self.request('GET', '/volumes/' + quote(assets_volume, safe='')).get('Labels', {})
        if labels.get('io.dst.managed') != 'true' or labels.get('io.dst.component') != 'official-assets':
            raise ValueError('Official asset storage is not owned.')
        image = 'dst-docker-assets:local'
        definition = self.request('GET', '/images/' + quote(image, safe='') + '/json')
        if definition.get('Config', {}).get('Labels', {}).get('io.dst.asset-installer') != 'true':
            raise ValueError('Build the packaged official asset installer first.')
        return self.request('POST', '/containers/create?name=dst-' + project + '-asset-stage-' + operation[:16], {
            'Image': definition['Id'], 'User': '10001:10001',
            'Env': ['HOME=/home/dst', 'DST_ASSETS_STAGE_ID=' + operation, 'DST_EXPECTED_BUILD=' + build],
            'Labels': {'io.dst.managed':'true', 'io.dst.project':project, 'io.dst.component':'asset-stage', 'io.dst.stage':operation},
            'HostConfig': {'NetworkMode':'bridge', 'ReadonlyRootfs':True, 'Init':True, 'CapDrop':['ALL'],
                'SecurityOpt':['no-new-privileges:true'], 'RestartPolicy':{'Name':'no'},
                'Memory':2*1024**3, 'MemorySwap':2*1024**3, 'NanoCpus':2_000_000_000, 'PidsLimit':128,
                'Tmpfs':{'/tmp':'rw,nosuid,size=64m,uid=10001,gid=10001', '/home/dst':'rw,nosuid,size=256m,uid=10001,gid=10001'},
                'Mounts':[{'Type':'volume', 'Source':assets_volume, 'Target':'/srv/dst'}],
                'LogConfig':{'Type':'json-file','Config':{'max-size':'2m','max-file':'2'}}}})['Id']

    def iter_logs(self, identifier, expected_labels):
        observed = self.inspect(identifier)
        actual = observed.get('Config', {}).get('Labels', {})
        if not expected_labels or any(actual.get(key) != value for key, value in expected_labels.items()):
            raise EngineError('Log source is not owned by this installation.')
        tty = observed.get('Config', {}).get('Tty', False)
        connection = EngineConnection()
        try:
            connection.request('GET', '/containers/' + identifier + '/logs?stdout=1&stderr=1&timestamps=1&tail=all')
            response = connection.getresponse()
            if response.status != 200: raise EngineError('Container logs are unavailable.')
            while True:
                if tty:
                    chunk = response.read(65536)
                    if not chunk: break
                else:
                    header = response.read(8)
                    if not header: break
                    if len(header) != 8 or header[0] not in {1, 2} or header[1:4] != b'\0\0\0':
                        raise EngineError('Invalid container log stream.')
                    length = struct.unpack('>I', header[4:])[0]
                    if length > 2 * 1024 * 1024: raise EngineError('Container log frame is too large.')
                    chunk = response.read(length)
                    if len(chunk) != length: raise EngineError('Container log stream was interrupted.')
                yield chunk
        finally: connection.close()

    def create_scaler(self,project,network,control_volume):
        if not re.fullmatch(r'[a-f0-9]{32}',project) or network!='dst-'+project+'-network':raise ValueError('Invalid scaler scope.')
        owned=self.request('GET','/networks/'+network).get('Labels',{})
        if owned.get('io.dst.project')!=project or owned.get('io.dst.managed')!='true':raise EngineError('Scaler network is not owned.')
        volume=self.request('GET','/volumes/'+quote(control_volume,safe=''))
        if volume.get('Labels',{}).get('com.docker.compose.volume')!='dst-control':raise ValueError('Invalid scaler control storage.')
        image='dst-docker-scaler:local';definition=self.request('GET','/images/'+quote(image,safe='')+'/json')
        if definition.get('Config',{}).get('Labels',{}).get('io.dst.scaler')!='true':raise ValueError('Build the packaged scaler image first.')
        config_volume='dst-'+project+'-scaler-config';self.ensure_owned_volume(config_volume,project,'scaler-config')
        return self.request('POST','/containers/create?name=dst-'+project+'-scaler',{
            'Image':image,'Labels':{'io.dst.managed':'true','io.dst.project':project,'io.dst.component':'scaler'},
            'HostConfig':{'NetworkMode':network,'ReadonlyRootfs':True,'Init':True,'CapDrop':['ALL'],'SecurityOpt':['no-new-privileges:true'],
                'Memory':64*1024**2,'MemorySwap':64*1024**2,'NanoCpus':250_000_000,'PidsLimit':24,
                'Mounts':[{'Type':'volume','Source':control_volume,'Target':'/control','ReadOnly':True},
                          {'Type':'volume','Source':config_volume,'Target':'/etc/dst-scaler'}],
                'RestartPolicy':{'Name':'no'},'LogConfig':{'Type':'json-file','Config':{'max-size':'2m','max-file':'2'}}}})['Id']

    def remove_map_observer(self,identifier,project,partition):
        if type(partition) is not int or partition not in {1,8}:raise ValueError('Invalid map observer partition.')
        observed=self.assert_owned(identifier,project,'map-observer-'+str(partition))
        if observed['State']['Status']=='running':self.lifecycle(identifier,project,'stop')
        # Only this ephemeral observer is removed; no game or persistent volume.
        self.request('DELETE','/containers/'+identifier,expected=(204,))

    def create_map_observer(self,project,partition,game,control_volume):
        if not re.fullmatch(r'[a-f0-9]{32}',project) or type(partition) is not int or partition not in {1,8}:
            raise ValueError('Invalid native map observer identity.')
        target=self.assert_owned(game,project,'game-'+str(partition))
        if target['State']['Status']!='running':raise ValueError('Start this map before its native observer.')
        own_volume=self.request('GET','/volumes/'+quote(control_volume,safe=''))
        if own_volume.get('Labels',{}).get('com.docker.compose.volume')!='dst-map-control':
            raise ValueError('Invalid map observation control storage.')
        image='dst-docker-map-observer:local'
        definition=self.request('GET','/images/'+quote(image,safe='')+'/json')
        if definition.get('Config',{}).get('Labels',{}).get('io.dst.map-observer')!='true':
            raise ValueError('Build the packaged map observer image first.')
        return self.request('POST','/containers/create?name=dst-'+project+'-map-observer-'+str(partition),{
            'Image':image,'Env':['DST_MAP_PARTITION='+str(partition)],
            'Labels':{'io.dst.managed':'true','io.dst.project':project,'io.dst.component':'map-observer-'+str(partition)},
            'HostConfig':{'NetworkMode':'none','PidMode':'container:'+game,'ReadonlyRootfs':True,'Init':True,
                'CapDrop':['ALL'],'CapAdd':['SYS_PTRACE','DAC_READ_SEARCH'],'GroupAdd':['10001'],
                'SecurityOpt':['no-new-privileges:true'],'Memory':256*1024**2,'MemorySwap':256*1024**2,
                'NanoCpus':500_000_000,'PidsLimit':48,
                'Tmpfs':{'/tmp':'rw,nosuid,size=96m','/var/lib/dst-atlas':'rw,exec,nosuid,size=8m,mode=755'},
                'Mounts':[{'Type':'volume','Source':control_volume,'Target':'/control'}],
                'RestartPolicy':{'Name':'no'},'LogConfig':{'Type':'json-file','Config':{'max-size':'2m','max-file':'2'}}}})['Id']

    def create_restore_job(self,project,image,network,state_volume,backup_volume,script,operation,target,name,expected_sha,
                           before_name,expected_counts,qualification=False,fault='',mode='restore',recovery=None):
        if not re.fullmatch(r'[a-f0-9]{32}',project) or not re.fullmatch(r'[a-f0-9]{32}',operation):raise ValueError('Invalid restore identity.')
        if not re.fullmatch(r'registry\.funcom\.com/funcom/self-hosting/seabass-server-db-utils:[A-Za-z0-9_.-]+',image):
            raise ValueError('Restore tools must come from the official package.')
        if network!='dst-'+project+'-network' or backup_volume!='dst-'+project+'-backups':raise ValueError('Invalid restore resources.')
        if type(qualification) is not bool or not(target=='dune' and not qualification or qualification and re.fullmatch(r'dst_qualify_[a-f0-9]{24}',target)):
            raise ValueError('Invalid restore target scope.')
        if mode not in {'restore','recover'} or fault not in {'','before-promotion','after-promotion','kill-after-promotion'} or fault and not qualification:
            raise ValueError('Invalid internal restore mode.')
        if not all(isinstance(value,str) and re.fullmatch(r'backup-[0-9]+-[a-f0-9]{8}\.dump',value) for value in [name,before_name]):
            raise ValueError('Invalid restore backup name.')
        if not isinstance(expected_sha,str) or not re.fullmatch(r'[a-f0-9]{64}',expected_sha):raise ValueError('Invalid restore checksum.')
        if not isinstance(expected_counts,dict) or set(expected_counts)!={'duneTables','duneViews','partitions','players'} or any(type(value) is not int or value<0 for value in expected_counts.values()):
            raise ValueError('A verified restore manifest is required.')
        environment=['DST_PROJECT_ID='+project,'DST_OPERATION_ID='+operation,'DST_DATABASE_HOST=dst-'+project+'-postgres',
                     'DST_TARGET_DATABASE='+target,'DST_BACKUP_NAME='+name,'DST_EXPECTED_SHA256='+expected_sha,
                     'DST_BEFORE_BACKUP_NAME='+before_name,'DST_EXPECTED_COUNTS='+json.dumps(expected_counts),
                     'DST_RESTORE_MODE='+mode]
        if qualification:environment.append('DST_QUALIFICATION=1')
        if fault:environment.append('DST_RESTORE_FAULT='+fault)
        if mode=='recover':
            if not isinstance(recovery,dict) or any(type(recovery.get(key)) is not int or recovery[key]<=0 for key in ['originalOid','stageOid']):
                raise ValueError('Verified recovery identities are required.')
            environment+=['DST_ORIGINAL_OID='+str(recovery['originalOid']),'DST_STAGE_OID='+str(recovery['stageOid']),
                          'DST_CONNECTIONS_FENCED='+('1' if recovery.get('connectionsFenced') else '0')]
        self.ensure_owned_volume(backup_volume,project,'backups')
        component='db-restore'
        identifier=self.request('POST','/containers/create?name=dst-'+project+'-restore-'+operation[:16]+'-'+secrets.token_hex(4),{
            'Image':image,'Entrypoint':['python3'],'Cmd':['/tmp/dst-restore.py'],'Env':environment,
            'Labels':{'io.dst.managed':'true','io.dst.project':project,'io.dst.component':component,'io.dst.operation':operation},
            'HostConfig':{'NetworkMode':network,'RestartPolicy':{'Name':'no'},
                          'Mounts':[{'Type':'volume','Source':state_volume,'Target':'/run/dst','ReadOnly':True},
                                    {'Type':'volume','Source':backup_volume,'Target':'/backups'}],
                          'LogConfig':{'Type':'json-file','Config':{'max-size':'10m','max-file':'2'}}}})['Id']
        self.upload_component_files(identifier,project,component,{'tmp/dst-restore.py':{'data':script}})
        return identifier

    def game_heartbeats(self,identifier,project):
        self.assert_owned(identifier,project,'director')
        connection=EngineConnection()
        try:
            connection.request('GET','/containers/'+identifier+'/logs?stdout=1&stderr=1&since='+str(int(time.time())-35)+'&tail=3000')
            response=connection.getresponse();raw=response.read(1024*1024)
            if response.status!=200:raise EngineError('Game heartbeat observations are unavailable.')
        finally:connection.close()
        output=[];offset=0
        while offset+8<=len(raw):
            length=struct.unpack('>I',raw[offset+4:offset+8])[0];offset+=8
            if length>len(raw)-offset:break
            output.append(raw[offset:offset+length]);offset+=length
        now=time.time();result={}
        for line in b''.join(output).decode('utf-8','replace').splitlines():
            marker='Received server state: '
            if marker not in line:continue
            try:
                message=json.loads(line.split(marker,1)[1]);partition=message['partitionId'];stamp=message['reportTimestamp']
                if type(partition) is not int or partition<=0 or type(stamp) not in {int,float} or not now-35<=stamp<=now+5:continue
                if type(message.get('ready')) is not bool or not isinstance(message.get('players'),list):continue
                if partition not in result or stamp>result[partition]['observedAt']:
                    result[partition]={'ready':message['ready'],'players':len(message['players']),'observedAt':stamp}
                    # The game reports its generated 22-character server GUID,
                    # independently of POD_UID. Retain only that identity;
                    # passwords and per-player heartbeat data stay private.
                    if isinstance(message.get('serverId'),str) and re.fullmatch(r'[A-Za-z0-9_+/-]{22}',message['serverId']):
                        result[partition]['serverId']=message['serverId']
            except (ValueError,KeyError,TypeError):continue
        return result

    def create_backup_job(self, project, image, network, state_volume, backup_volume, script, mode, name, expected_sha=None, retain_database=False,request_id=None):
        if not re.fullmatch(r'[a-f0-9]{32}',project) or mode not in {'create','verify'}:
            raise ValueError('Invalid owned backup job.')
        if not re.fullmatch(r'registry\.funcom\.com/funcom/self-hosting/seabass-server-db-utils:[A-Za-z0-9_.-]+',image):
            raise ValueError('Backup tools must come from the official package.')
        if network!='dst-'+project+'-network' or backup_volume!='dst-'+project+'-backups':raise ValueError('Invalid backup storage.')
        if not re.fullmatch(r'backup-[0-9]+-[a-f0-9]{8}\.dump',name):raise ValueError('Invalid backup name.')
        if type(retain_database) is not bool or (retain_database and mode!='verify'):
            raise ValueError('A retained database requires an internal restore qualification job.')
        if request_id is not None and (mode!='create' or not isinstance(request_id,str) or not re.fullmatch(r'[a-f0-9]{32}',request_id)):
            raise ValueError('Invalid scheduled backup identity.')
        environment=['DST_DATABASE_HOST=dst-'+project+'-postgres','DST_BACKUP_MODE='+mode,'DST_BACKUP_NAME='+name]
        if mode=='verify':
            if not isinstance(expected_sha,str) or not re.fullmatch(r'[a-f0-9]{64}',expected_sha):raise ValueError('Invalid backup checksum.')
            environment+=['DST_EXPECTED_SHA256='+expected_sha,'DST_VERIFY_DATABASE='+('dst_qualify_' if retain_database else 'dst_verify_')+secrets.token_hex(12)]
            if retain_database:environment.append('DST_RETAIN_VERIFICATION=1')
        self.ensure_owned_volume(backup_volume,project,'backups')
        component='db-backup' if mode=='create' else 'db-verify'
        job_name='dst-'+project+'-'+component+'-'+(request_id or secrets.token_hex(4))
        def existing():
            found=self.request('GET','/containers/'+job_name+'/json',expected=(200,404))
            if not found or not found.get('Id'):return None
            self.assert_owned(found['Id'],project,component)
            mounts=found.get('Mounts',[])
            if (found.get('Config',{}).get('Image')!=image or found.get('Config',{}).get('Cmd')!=['/tmp/dst-job.py'] or
                not all(value in found.get('Config',{}).get('Env',[]) for value in environment) or
                found.get('HostConfig',{}).get('NetworkMode')!=network or len(mounts)!=2 or
                {(row.get('Name'),row.get('Destination')) for row in mounts}!={(state_volume,'/run/dst'),(backup_volume,'/backups')}):
                raise EngineError('The scheduled backup identity does not match its owned job.')
            return found
        found=existing() if request_id else None
        if found:
            if found['State']['Status']=='created':self.upload_component_files(found['Id'],project,component,{'tmp/dst-job.py':{'data':script}})
            return found['Id']
        try:identifier=self.request('POST','/containers/create?name='+job_name,{
            'Image':image,'Entrypoint':['python3'],'Cmd':['/tmp/dst-job.py'],'Env':environment,
            'Labels':{'io.dst.managed':'true','io.dst.project':project,'io.dst.component':component},
            'HostConfig':{'NetworkMode':network,'RestartPolicy':{'Name':'no'},
                          'Mounts':[{'Type':'volume','Source':state_volume,'Target':'/run/dst','ReadOnly':True},
                                    {'Type':'volume','Source':backup_volume,'Target':'/backups','ReadOnly':mode=='verify'}],
                          'LogConfig':{'Type':'json-file','Config':{'max-size':'10m','max-file':'2'}}}})['Id']
        except EngineError:
            found=existing() if request_id else None
            if not found:raise
            if found['State']['Status']=='created':self.upload_component_files(found['Id'],project,component,{'tmp/dst-job.py':{'data':script}})
            return found['Id']
        self.upload_component_files(identifier,project,component,{'tmp/dst-job.py':{'data':script}})
        return identifier

    def create_backup_cleanup_job(self,project,files,request_id):
        if not re.fullmatch(r'[a-f0-9]{32}',project) or not isinstance(request_id,str) or not re.fullmatch(r'[a-f0-9]{32}',request_id) or not isinstance(files,list) or not 1<=len(files)<=100:
            raise ValueError('Invalid backup cleanup request.')
        for row in files:
            if not isinstance(row,dict) or not re.fullmatch(r'backup-[0-9]+-[a-f0-9]{8}\.dump',str(row.get('name',''))) or not re.fullmatch(r'[a-f0-9]{64}',str(row.get('sha256',''))):
                raise ValueError('Choose recorded backup files and checksums.')
        volume='dst-'+project+'-backups'
        labels=self.request('GET','/volumes/'+volume).get('Labels') or {}
        if labels.get('io.dst.managed')!='true' or labels.get('io.dst.project')!=project:
            raise EngineError('Backup storage does not belong to this installation.')
        own=self.inspect(os.environ['HOSTNAME'])
        name='dst-'+project+'-db-files-'+request_id
        payload=json.dumps(files)
        def existing():
            found=self.request('GET','/containers/'+name+'/json',expected=(200,404))
            if not found or not found.get('Id'):return None
            self.assert_owned(found['Id'],project,'db-files')
            mounts=found.get('Mounts',[])
            if (found.get('Config',{}).get('Cmd')!=['-B','/opt/dst-manager/backup_storage.py'] or
                'DST_BACKUP_FILES='+payload not in found.get('Config',{}).get('Env',[]) or
                found.get('HostConfig',{}).get('NetworkMode')!='none' or len(mounts)!=1 or
                mounts[0].get('Type')!='volume' or mounts[0].get('Name')!=volume or mounts[0].get('Destination')!='/backups'):
                raise EngineError('The recorded backup cleanup identity does not match its owned job.')
            return found['Id']
        found=existing()
        if found:return found
        try:identifier=self.request('POST','/containers/create?name='+name,{
            'Image':own['Image'],'User':'0:0','Entrypoint':['python3'],'Cmd':['-B','/opt/dst-manager/backup_storage.py'],
            'Env':['DST_BACKUP_FILES='+payload],
            'Labels':{'io.dst.managed':'true','io.dst.project':project,'io.dst.component':'db-files'},
            'HostConfig':{'NetworkMode':'none','CapDrop':['ALL'],'SecurityOpt':['no-new-privileges:true'],
                          'Memory':128*1024**2,'MemorySwap':128*1024**2,'NanoCpus':1_000_000_000,'PidsLimit':16,
                          'Mounts':[{'Type':'volume','Source':volume,'Target':'/backups'}],
                          'RestartPolicy':{'Name':'no'},'LogConfig':{'Type':'json-file','Config':{'max-size':'1m','max-file':'2'}}}})['Id']
        except EngineError:
            found=existing()
            if found:return found
            raise
        # Fixed script in the manager image, never a client command or socket.
        return identifier

    def create_backup_export_job(self,project,request):
        if (not re.fullmatch(r'[a-f0-9]{32}',project) or not isinstance(request,dict) or
            not re.fullmatch(r'[a-f0-9]{32}',str(request.get('id',''))) or
            not re.fullmatch(r'backup-[0-9]+-[a-f0-9]{8}\.dump',str(request.get('name',''))) or
            not re.fullmatch(r'[a-f0-9]{64}',str(request.get('sha256',''))) or
            type(request.get('bytes')) is not int or request['bytes']<=0):
            raise ValueError('Choose a recorded completed backup export.')
        volume='dst-'+project+'-backups'
        labels=self.request('GET','/volumes/'+volume).get('Labels') or {}
        if labels.get('io.dst.managed')!='true' or labels.get('io.dst.project')!=project:raise EngineError('Backup storage is not owned.')
        own=self.inspect(os.environ['HOSTNAME'])
        control=[row for row in own.get('Mounts',[]) if row.get('Type')=='volume' and row.get('Destination')=='/control']
        if len(control)!=1:raise ValueError('Private export storage is unavailable.')
        definition=self.request('GET','/volumes/'+control[0]['Name'])
        if (definition.get('Labels') or {}).get('com.docker.compose.volume')!='dst-control':raise ValueError('Private export storage is not the control volume.')
        name='dst-'+project+'-db-export-'+request['id'];payload=json.dumps(request)
        def existing():
            found=self.request('GET','/containers/'+name+'/json',expected=(200,404))
            if not found or not found.get('Id'):return None
            self.assert_owned(found['Id'],project,'db-export')
            mounts=found.get('HostConfig',{}).get('Mounts',[])
            if (found.get('Config',{}).get('Cmd')!=['-B','/opt/dst-manager/backup_storage.py'] or
                'DST_BACKUP_EXPORT='+payload not in found.get('Config',{}).get('Env',[]) or len(mounts)!=2 or
                found.get('HostConfig',{}).get('NetworkMode')!='none' or
                not any(row.get('Source')==volume and row.get('Target')=='/backups' and row.get('ReadOnly') is True for row in mounts) or
                not any(row.get('Source')==control[0]['Name'] and row.get('Target')=='/exports' and row.get('VolumeOptions',{}).get('Subpath')=='backup-exports' for row in mounts)):
                raise EngineError('The recorded export does not match its owned job.')
            return found['Id']
        found=existing()
        if found:return found
        try:return self.request('POST','/containers/create?name='+name,{
            'Image':own['Image'],'User':'0:0','Entrypoint':['python3'],'Cmd':['-B','/opt/dst-manager/backup_storage.py'],
            'Env':['DST_BACKUP_EXPORT='+payload],
            'Labels':{'io.dst.managed':'true','io.dst.project':project,'io.dst.component':'db-export'},
            'HostConfig':{'NetworkMode':'none','CapDrop':['ALL'],'SecurityOpt':['no-new-privileges:true'],
                          'Memory':128*1024**2,'MemorySwap':128*1024**2,'NanoCpus':1_000_000_000,'PidsLimit':16,
                          'Mounts':[{'Type':'volume','Source':volume,'Target':'/backups','ReadOnly':True},
                                    {'Type':'volume','Source':control[0]['Name'],'Target':'/exports','VolumeOptions':{'Subpath':'backup-exports'}}],
                          'RestartPolicy':{'Name':'no'},'LogConfig':{'Type':'json-file','Config':{'max-size':'1m','max-file':'2'}}}})['Id']
        except EngineError:
            found=existing()
            if found:return found
            raise

    def create_backup_import_job(self,project,image,request,script):
        if (not re.fullmatch(r'[a-f0-9]{32}',project) or
            not re.fullmatch(r'registry\.funcom\.com/funcom/self-hosting/seabass-server-db-utils:[A-Za-z0-9_.-]+',image) or
            not isinstance(request,dict) or not re.fullmatch(r'[a-f0-9]{32}',str(request.get('uploadId',''))) or
            not re.fullmatch(r'backup-[0-9]+-[a-f0-9]{8}\.dump',str(request.get('name',''))) or
            not re.fullmatch(r'[a-f0-9]{64}',str(request.get('sha256',''))) or type(request.get('bytes')) is not int or not 5<=request['bytes']<=25*1024**3):
            raise ValueError('Choose a bounded, owned PostgreSQL backup import.')
        own=self.inspect(os.environ['HOSTNAME']);compose=(own.get('Config',{}).get('Labels') or {}).get('com.docker.compose.project','')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}',compose):raise ValueError('The application installation identity is unavailable.')
        filters=quote(json.dumps({'label':['com.docker.compose.project='+compose,'com.docker.compose.service=dst']}),safe='')
        applications=self.request('GET','/containers/json?all=true&filters='+filters)
        if len(applications)!=1:raise ValueError('Exactly one application instance is required for browser backup imports.')
        app=self.inspect(applications[0]['Id'])
        mounts=[row for row in app.get('Mounts',[]) if row.get('Type')=='volume' and row.get('Destination')=='/data/cache']
        if len(mounts)!=1:raise ValueError('The application upload cache is unavailable.')
        cache=mounts[0]['Name'];labels=self.request('GET','/volumes/'+cache).get('Labels') or {}
        if labels.get('com.docker.compose.project')!=compose or labels.get('com.docker.compose.volume')!='dst-cache':raise ValueError('The selected upload cache does not belong to this installation.')
        volume='dst-'+project+'-backups';self.ensure_owned_volume(volume,project,'backups')
        payload=json.dumps(request);name='dst-'+project+'-db-import-'+request['uploadId']
        def existing():
            found=self.request('GET','/containers/'+name+'/json',expected=(200,404))
            if not found or not found.get('Id'):return None
            self.assert_owned(found['Id'],project,'db-import')
            mounts=found.get('HostConfig',{}).get('Mounts',[])
            if (found.get('Config',{}).get('Image')!=image or found.get('Config',{}).get('Cmd')!=['/tmp/dst-job.py'] or
                'DST_BACKUP_IMPORT='+payload not in found.get('Config',{}).get('Env',[]) or
                found.get('HostConfig',{}).get('NetworkMode')!='none' or len(mounts)!=2 or
                not any(row.get('Source')==cache and row.get('Target')=='/incoming' and row.get('ReadOnly') is True and row.get('VolumeOptions',{}).get('Subpath')=='backup-transfers' for row in mounts) or
                not any(row.get('Source')==volume and row.get('Target')=='/backups' for row in mounts)):
                raise EngineError('The recorded import does not match its owned job.')
            return found
        found=existing()
        if found:
            if found['State']['Status']=='created':self.upload_component_files(found['Id'],project,'db-import',{'tmp/dst-job.py':{'data':script}})
            return found['Id']
        try:identifier=self.request('POST','/containers/create?name='+name,{
            'Image':image,'User':'0:10001','Entrypoint':['python3'],'Cmd':['/tmp/dst-job.py'],'Env':['DST_BACKUP_IMPORT='+payload],
            'Labels':{'io.dst.managed':'true','io.dst.project':project,'io.dst.component':'db-import'},
            'HostConfig':{'NetworkMode':'none','CapDrop':['ALL'],'SecurityOpt':['no-new-privileges:true'],
                          'Memory':256*1024**2,'MemorySwap':256*1024**2,'NanoCpus':1_000_000_000,'PidsLimit':24,
                          'Mounts':[{'Type':'volume','Source':cache,'Target':'/incoming','ReadOnly':True,'VolumeOptions':{'Subpath':'backup-transfers'}},
                                    {'Type':'volume','Source':volume,'Target':'/backups'}],
                          'RestartPolicy':{'Name':'no'},'LogConfig':{'Type':'json-file','Config':{'max-size':'1m','max-file':'2'}}}})['Id']
        except EngineError:
            found=existing()
            if not found:raise
            if found['State']['Status']=='created':self.upload_component_files(found['Id'],project,'db-import',{'tmp/dst-job.py':{'data':script}})
            return found['Id']
        self.upload_component_files(identifier,project,'db-import',{'tmp/dst-job.py':{'data':script}})
        return identifier

    def mirror_destination(self):
        import mirror_jobs
        return mirror_jobs.destination(self)

    def create_backup_mirror_job(self,project,request):
        import mirror_jobs
        return mirror_jobs.create(self,project,request)

    def backup_report(self,identifier,project,component):
        if component not in {'db-backup','db-verify','db-restore','db-migrate','db-files','db-export','db-import','db-mirror','host-memory-swap'}:raise ValueError('Invalid backup report component.')
        self.assert_owned(identifier,project,component)
        connection=EngineConnection()
        try:
            connection.request('GET','/containers/'+identifier+'/archive?path=/tmp/dst-result.json')
            response=connection.getresponse();raw=response.read(262145)
            if response.status!=200 or len(raw)>262144:raise EngineError('Backup report is unavailable.')
        finally:connection.close()
        try:
            with tarfile.open(fileobj=io.BytesIO(raw),mode='r:*') as archive:
                members=archive.getmembers()
                if len(members)!=1 or not members[0].isfile() or members[0].size>65536:
                    raise EngineError('Backup report format is invalid.')
                result=json.loads(archive.extractfile(members[0]).read())
                if not isinstance(result,dict):raise EngineError('Backup report format is invalid.')
                return result
        except (tarfile.TarError,ValueError,OSError):raise EngineError('Backup report format is invalid.') from None

    def backup_jobs(self,project):
        if not re.fullmatch(r'[a-f0-9]{32}',project):raise ValueError('Invalid backup project.')
        filters=quote(json.dumps({'label':['io.dst.project='+project,'io.dst.managed=true']}),safe='')
        rows=self.request('GET','/containers/json?all=true&filters='+filters)
        result=[]
        for row in rows:
            component=(row.get('Labels') or {}).get('io.dst.component')
            if component not in {'db-backup','db-verify','db-files','db-restore','db-export','db-import','db-mirror'}:continue
            result.append({'id':row['Id'],'name':(row.get('Names') or [''])[0].lstrip('/'),
                           'component':component,'createdAt':row['Created'],'state':row['State']})
        return sorted(result,key=lambda row:(row['createdAt'],row['id']),reverse=True)

    def remove_backup_job(self,project,job):
        if job.get('component') not in {'db-backup','db-verify','db-files','db-restore','db-export','db-import','db-mirror'}:raise ValueError('Only backup helper jobs may be cleaned up.')
        observed=self.assert_owned(job['id'],project,job['component'])
        if observed['State']['Status']!='exited':raise ValueError('A backup helper must finish before cleanup.')
        # No force and no volume deletion. A start race is rejected by Docker.
        self.request('DELETE','/containers/'+job['id']+'?v=false',expected=(204,))

    def ensure_owned_volume(self, name, project, component):
        if not name.startswith('dst-'+project+'-') or not re.fullmatch(r'[a-f0-9]{32}',project):
            raise ValueError('Invalid project volume.')
        found=self.request('GET','/volumes/'+quote(name,safe=''),expected=(200,404))
        if found and found.get('Name'):
            labels=found.get('Labels') or {}
            if labels.get('io.dst.managed')!='true' or labels.get('io.dst.project')!=project:
                raise EngineError('Existing volume is not owned by this DST installation.')
            return
        self.request('POST','/volumes/create',{'Name':name,'Labels':{
            'io.dst.managed':'true','io.dst.project':project,'io.dst.component':component}})

    def create_component(self, project, component, image, network, environment, command=None, ports=None,
                         volumes=None, memory=0, host_network=False, entrypoint=None, health=None, map_name=None,generation=None,regis_image=None,memory_swap=None):
        # Internal API only. The Unix/browser dispatcher never accepts these
        # arguments from a client; it derives them from the official template.
        expected={'rmq-admin':'seabass-server-rabbitmq','rmq-game':'seabass-server-rabbitmq',
                  'director':'seabass-server-bg-director','text-router':'seabass-server-text-router',
                  'gateway':'seabass-server-gateway'}
        game=bool(re.fullmatch(r'game-[1-9][0-9]*',component))
        if generation is not None and not re.fullmatch(r'[a-f0-9]{32}',generation):raise ValueError('Invalid component generation.')
        image_name='seabass-server' if game else expected.get(component)
        if not re.fullmatch(r'[a-f0-9]{32}',project) or not image_name or not re.fullmatch(
                re.escape('registry.funcom.com/funcom/self-hosting/'+image_name)+r':[A-Za-z0-9_.-]+',image):
            raise ValueError('Invalid official world component.')
        effective_image=image
        if regis_image is not None:
            if not game or map_name!='Survival_1':raise ValueError('Tank compatibility is limited to owned Hagga game adapters.')
            from regis_artifacts import inspect_compatibility_image
            effective_image=inspect_compatibility_image(self,project,image,regis_image)['Id']
        if network!='dst-'+project+'-network' or (host_network and not game): raise ValueError('Invalid component network.')
        if game and (not isinstance(map_name,str) or not re.fullmatch(r'[A-Za-z0-9_]+',map_name)):
            raise ValueError('Invalid game map label.')
        observed=self.request('GET','/networks/'+network)
        labels=observed.get('Labels') or {}
        if labels.get('io.dst.project')!=project or labels.get('io.dst.managed')!='true':
            raise EngineError('World network is not owned by this installation.')
        bindings={}
        for port in ports or []:
            if type(port['host']) is not int or not 1024<=port['host']<=65535 or port['ip'] not in {'127.0.0.1','0.0.0.0'}:
                raise ValueError('Invalid component port binding.')
            key=str(port['container'])+'/tcp'
            bindings[key]=[{'HostIp':port['ip'],'HostPort':str(port['host'])}]
        mounts=[]
        for volume in volumes or []:
            if volume.get('mustBeNew'):
                found=self.request('GET','/volumes/'+quote(volume['name'],safe=''),expected=(200,404))
                if found and found.get('Name'):
                    raise EngineError('Existing game storage was preserved; its initialization needs review.')
            subpath=volume.get('subpath')
            if subpath is not None:
                if not game or component=='game-1' or subpath!='UserSettings' or volume['name']!='dst-'+project+'-game-1-saved' or volume['target']!='/home/dune/server/DuneSandbox/Saved/UserSettings':
                    raise ValueError('Invalid shared server settings mount.')
                found=self.request('GET','/volumes/'+quote(volume['name'],safe=''))
                labels=found.get('Labels') or {}
                if labels.get('io.dst.managed')!='true' or labels.get('io.dst.project')!=project:
                    raise EngineError('The shared settings volume is not owned.')
            else:self.ensure_owned_volume(volume['name'],project,component)
            mount={'Type':'volume','Source':volume['name'],'Target':volume['target'],'ReadOnly':volume.get('readOnly',False)}
            if subpath:mount['VolumeOptions']={'Subpath':subpath}
            mounts.append(mount)
        host={'NetworkMode':'host' if host_network else network,'RestartPolicy':{'Name':'no'},
              'PortBindings':bindings,'Mounts':mounts,'LogConfig':{'Type':'json-file','Config':{'max-size':'20m','max-file':'3'}}}
        if game:host['Init']=True
        if memory:
            if type(memory) is not int or memory<64*1024*1024: raise ValueError('Invalid component memory budget.')
            import memory_swap as swap_policy
            total=swap_policy.total_limit(memory) if game and memory_swap is None else memory if memory_swap is None else memory_swap
            if type(total) is not int or total<memory:raise ValueError('Invalid combined RAM and swap limit.')
            host.update(Memory=memory,MemorySwap=total)
        spec={'Image':effective_image,'Env':[key+'='+value for key,value in environment.items()],
              'Labels':{'io.dst.managed':'true','io.dst.project':project,'io.dst.component':component},
              'ExposedPorts':{key:{} for key in bindings},'HostConfig':host,'StopTimeout':120 if game else 30}
        if game:
            spec['Labels']['io.dst.map']=map_name
        if regis_image is not None:spec['Labels']['io.dst.regis.image']=effective_image
        if generation is not None:spec['Labels']['io.dst.generation']=generation
        if command is not None: spec['Cmd']=command
        if entrypoint is not None: spec['Entrypoint']=entrypoint
        if health is not None: spec['Healthcheck']=health
        return self.request('POST','/containers/create?name=dst-'+project+'-'+component,spec)['Id']

    def upload_component_files(self, identifier, project, component, files, destination='/'):
        if destination!='/' and (component!='scaler' or destination!='/etc/dst-scaler'):raise ValueError('Invalid internal configuration destination.')
        self.assert_owned(identifier,project,component)
        buffer=io.BytesIO()
        with tarfile.open(fileobj=buffer,mode='w') as archive:
            for filename,settings in files.items():
                path=Path(filename)
                if path.is_absolute() or '..' in path.parts: raise ValueError('Invalid internal component file.')
                member=tarfile.TarInfo(filename)
                if settings.get('directory') is True:
                    member.type=tarfile.DIRTYPE;data=b''
                else:
                    data=settings['data']
                    if isinstance(data,str): data=data.encode('utf-8')
                member.size=len(data)
                member.mode=settings.get('mode',0o444);member.uid=settings.get('uid',0);member.gid=settings.get('gid',0)
                archive.addfile(member,io.BytesIO(data))
        connection=EngineConnection()
        try:
            connection.request('PUT','/containers/'+identifier+'/archive?path='+quote(destination,safe='/'),buffer.getvalue(),{'Content-Type':'application/x-tar'})
            response=connection.getresponse(); response.read()
            if response.status!=200: raise EngineError('World component files could not be prepared.')
        finally: connection.close()

    def create_migration_job(self, project, image, network, state_volume, database_name, script, backup_volume, backup_name,operation=None):
        if not re.fullmatch(r'[a-f0-9]{32}', project): raise ValueError('Invalid project identity.')
        if not re.fullmatch(r'registry\.funcom\.com/funcom/self-hosting/seabass-server-db-utils:[A-Za-z0-9_.-]+', image):
            raise ValueError('Migration requires the official database utilities image.')
        if operation is not None and (not isinstance(operation,str) or not re.fullmatch(r'[a-f0-9]{32}',operation)):
            raise ValueError('Invalid migration operation identity.')
        name='dst-'+project+'-db-migrate-'+(operation[:16] if operation else secrets.token_hex(4))
        environment=['DST_DATABASE_HOST='+database_name,'DST_BACKUP_NAME='+backup_name]
        labels={'io.dst.managed':'true','io.dst.project':project,'io.dst.component':'db-migrate'}
        if operation:
            environment.append('DST_OPERATION_ID='+operation);labels['io.dst.operation']=operation
            labels['io.dst.script-sha256']=hashlib.sha256(script.encode('utf-8')).hexdigest()
            existing=self.request('GET','/containers/'+name+'/json',expected=(200,404))
            if existing:
                found=existing.get('Config',{});actual=found.get('Labels',{})
                if any(actual.get(key)!=value for key,value in labels.items()) or found.get('Image')!=image or any(value not in found.get('Env',[]) for value in environment):
                    raise ValueError('The migration name belongs to a different operation or backup.')
                if existing.get('State',{}).get('Status')=='created':
                    self.upload_component_files(existing['Id'],project,'db-migrate',{'tmp/dst-job.py':{'data':script}})
                return existing['Id']
        self.ensure_owned_volume(backup_volume,project,'backups')
        created=self.request('POST','/containers/create?name='+name,{
            'Image':image,'Entrypoint':['python3'],'Cmd':['/tmp/dst-job.py'],
            'Env':environment,'Labels':labels,
            'HostConfig':{'NetworkMode':network,'RestartPolicy':{'Name':'no'},
                          'Mounts':[{'Type':'volume','Source':state_volume,'Target':'/run/dst','ReadOnly':True},
                                    {'Type':'volume','Source':backup_volume,'Target':'/backups'}],
                          'LogConfig':{'Type':'json-file','Config':{'max-size':'10m','max-file':'2'}}}})
        identifier=created['Id']
        self.upload_component_files(identifier,project,'db-migrate',{'tmp/dst-job.py':{'data':script,'mode':0o444}})
        return identifier

    def ensure_package_image(self, archive, image):
        path = Path(archive).resolve()
        if not path.is_relative_to(Path('/assets/server/images')) or not path.is_file():
            raise ValueError('Official image archive is unavailable.')
        found = self.request('GET', '/images/' + quote(image, safe='') + '/json', expected=(200,404))
        if image in (found or {}).get('RepoTags', []): return
        connection = EngineConnection()
        connection.timeout = 120
        try:
            with path.open('rb') as source:
                connection.request('POST','/images/load?quiet=1',source,
                                   {'Content-Type':'application/x-tar','Content-Length':str(path.stat().st_size)})
                response=connection.getresponse()
                result=response.read(8*1024*1024)
                if response.status != 200: raise EngineError('Official image could not be loaded.')
                for line in result.splitlines():
                    if json.loads(line).get('error'): raise EngineError('Official image load failed.')
        finally: connection.close()
        verified=self.request('GET','/images/'+quote(image,safe='')+'/json')
        if image not in verified.get('RepoTags',[]): raise EngineError('Loaded image identity could not be verified.')

    def request(self, method, path, body=None, expected=(200, 201, 204), timeout=30):
        connection = EngineConnection()
        connection.timeout=timeout
        try:
            payload = None if body is None else json.dumps(body).encode('utf-8')
            connection.request(method, path, payload, {'Content-Type': 'application/json'})
            response = connection.getresponse()
            raw = response.read(8 * 1024 * 1024)
            if response.status not in expected:
                # Daemon responses may describe paths/configuration: keep them
                # private rather than returning them to browser clients.
                raise EngineError(f'Docker operation failed ({response.status}).')
            if response.status==404:return None
            return json.loads(raw) if raw else None
        finally: connection.close()

    def inspect(self, identifier):
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', identifier):
            raise ValueError('Invalid container identifier.')
        return self.request('GET', '/containers/' + quote(identifier, safe='') + '/json')

    def set_director_floor(self,scaler,director,project,map_name,floor):
        self.assert_owned(scaler,project,'scaler');self.assert_owned(director,project,'director')
        payload={'host':'dst-'+project+'-director','map':map_name,'floor':floor}
        script=Path(__file__).with_name('director_policy.py').read_text()
        try:
            result=json.loads(self.exec_internal(scaler,project,'scaler',['python3','-c',script,json.dumps(payload)]))
        except (EngineError,ValueError):
            raise EngineError('The map setting was saved, but the director has not confirmed it yet. Wait for the director to finish starting, then retry the map control.') from None
        if result.get('applied') is not True:raise EngineError('The live director did not confirm the warm setting.')

    def exec_internal(self, identifier, project, component, command):
        self.assert_owned(identifier, project, component)
        settings={'AttachStdout':True,'AttachStderr':True,'Tty':False,'Cmd':command}
        created = self.request('POST', '/containers/' + identifier + '/exec',
                               settings)
        connection = EngineConnection()
        try:
            connection.request('POST', '/exec/' + created['Id'] + '/start',
                               json.dumps({'Detach': False, 'Tty': False}), {'Content-Type':'application/json'})
            response = connection.getresponse()
            if response.status != 200: raise EngineError('Internal database command could not start.')
            raw = response.read(8 * 1024 * 1024)
        finally: connection.close()
        stdout, stderr = [], []
        offset = 0
        while offset < len(raw):
            if len(raw) - offset < 8: raise EngineError('Incomplete Docker command output.')
            channel, length = raw[offset], struct.unpack('>I', raw[offset+4:offset+8])[0]
            offset += 8
            if length > len(raw) - offset: raise EngineError('Truncated Docker command output.')
            if channel == 1: stdout.append(raw[offset:offset+length])
            elif channel == 2: stderr.append(raw[offset:offset+length])
            offset += length
        status = self.request('GET', '/exec/' + created['Id'] + '/json')
        if status.get('Running') or status.get('ExitCode') != 0:
            raise EngineError('Internal database command failed. The server was left intact for recovery.')
        return b''.join(stdout).decode('utf-8')

    def assert_owned(self, identifier, project, component=None):
        container = self.inspect(identifier)
        labels = container.get('Config', {}).get('Labels') or {}
        if labels.get('io.dst.managed') != 'true' or labels.get('io.dst.project') != project:
            raise EngineError('Container is not owned by this DST installation.')
        if component and labels.get('io.dst.component') != component:
            raise EngineError('Container component does not match the requested action.')
        return container

    def lifecycle(self, identifier, project, action):
        if action not in {'start', 'stop', 'restart'}: raise ValueError('Unsupported lifecycle action.')
        observed=self.assert_owned(identifier, project)
        component=(observed.get('Config',{}).get('Labels') or {}).get('io.dst.component','')
        if action=='stop' and re.fullmatch(r'game-[1-9][0-9]*',component) and observed['State']['Status']=='running':
            return self.graceful_game_stop(identifier,project,component)
        # Preserve Funcom's 120-second shutdown grace. The manager journals
        # these long operations separately from the browser request lifetime.
        path='/containers/'+identifier+'/'+action
        if action in {'stop','restart'}:path+='?t=120'
        return self.request('POST',path,expected=(204,304),timeout=150 if action!='start' else 30)

    def graceful_game_stop(self,identifier,project,component):
        # Signal the verified native process inside this owned PID namespace,
        # including early launchers that still have a waiting runuser parent.
        # /proc/PID/exe can be hidden across UIDs even from container root.
        # ps reads the public process identity without granting ptrace rights.
        listing=self.exec_internal(identifier,project,component,['ps','-e','-o','pid=,uid=,comm='])
        candidates=[]
        for line in listing.splitlines():
            fields=line.split()
            if len(fields)==3 and fields[0].isdigit() and fields[1]=='1000' and fields[2] in {'DuneSandboxServ','GameThread'}:
                candidates.append(int(fields[0]))
        if len(candidates)!=1:
            if self.assert_owned(identifier,project,component)['State']['Status']=='exited':return
            raise EngineError('The owned game process could not be identified safely for shutdown.')
        try:self.exec_internal(identifier,project,component,['/bin/sh','-c','kill -TERM "$1"','dst-game-stop',str(candidates[0])])
        except EngineError:
            if self.assert_owned(identifier,project,component)['State']['Status']!='exited':raise
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            if self.assert_owned(identifier,project,component)['State']['Status']=='exited':return
            time.sleep(.5)
        # Match Docker/Kubernetes shutdown semantics after the full game grace
        # period. A stuck PreShutdown process must not leave the world half
        # stopped indefinitely. Recheck ownership before stopping that container.
        observed=self.assert_owned(identifier,project,component)
        if observed['State']['Status']=='exited':return
        if observed['State']['Status']!='running':
            raise EngineError('The game container changed state during shutdown and needs review.')
        self.request('POST','/containers/'+identifier+'/stop?t=0',expected=(204,304),timeout=30)
        if self.assert_owned(identifier,project,component)['State']['Status']!='exited':
            raise EngineError('The game container has not completed its stop.')

    def retire_game_container(self,identifier,project,component):
        if not re.fullmatch(r'game-[1-9][0-9]*',component):raise ValueError('Only an owned stopped game container can be replaced.')
        return self.retire_component(identifier,project,component)

    def retire_component(self,identifier,project,component):
        if component not in {'director','text-router','gateway','rmq-admin','rmq-game'} and not re.fullmatch(r'game-[1-9][0-9]*',component):
            raise ValueError('Unsupported replacement component.')
        observed=self.assert_owned(identifier,project,component)
        if observed['State']['Status'] not in {'exited','created'}:raise EngineError('Stop the component before replacing its adapter.')
        previous_name='dst-'+project+'-'+component+'-previous-'+secrets.token_hex(4)
        self.request('POST','/containers/'+identifier+'/rename?name='+previous_name)
        return previous_name

    def read_game_defaults(self,identifier,project):
        self.assert_owned(identifier,project,'game-1')
        result={}
        for key,name in [('game','DefaultGame.ini'),('engine','DefaultEngine.ini')]:
            connection=EngineConnection()
            try:
                connection.request('GET','/containers/'+identifier+'/archive?path=/home/dune/server/DuneSandbox/Config/'+name)
                response=connection.getresponse();raw=response.read(4*1024**2+1)
                if response.status!=200 or len(raw)>4*1024**2:raise EngineError('The selected server image defaults could not be read.')
            finally:connection.close()
            try:
                with tarfile.open(fileobj=io.BytesIO(raw),mode='r:*') as archive:
                    members=archive.getmembers()
                    if len(members)!=1 or not members[0].isfile() or members[0].size>2*1024**2:
                        raise EngineError('The server image defaults format needs review.')
                    result[key]=archive.extractfile(members[0]).read().decode('utf-8')
            except (tarfile.TarError,UnicodeError):raise EngineError('The selected server image defaults could not be read.') from None
        return {**result,'source':{'pod':'Docker installed game image','fetchedAt':time.time()},'cached':False}

    def read_director_config(self,identifier,project):
        self.assert_owned(identifier,project,'director')
        path='/Tools/Battlegroups/Director/BattlegroupDirector/director_config.ini'
        connection=EngineConnection()
        try:
            connection.request('GET','/containers/'+identifier+'/archive?path='+quote(path,safe='/'))
            response=connection.getresponse();raw=response.read(524289)
            if response.status!=200 or len(raw)>524288:raise EngineError('The existing director settings could not be preserved.')
        finally:connection.close()
        try:
            with tarfile.open(fileobj=io.BytesIO(raw),mode='r:*') as archive:
                members=archive.getmembers()
                if len(members)!=1 or not members[0].isfile() or members[0].size>262144:
                    raise EngineError('The existing director settings format needs review.')
                return archive.extractfile(members[0]).read()
        except tarfile.TarError:raise EngineError('The existing director settings could not be preserved.') from None

    def create_database(self, project, image, port, password):
        if not re.fullmatch(r'[a-f0-9]{32}', project): raise ValueError('Invalid project identity.')
        if not re.fullmatch(r'registry\.funcom\.com/funcom/self-hosting/igw-postgres:[A-Za-z0-9_.-]+', image):
            raise ValueError('Database image must come from the official self-host package.')
        if type(port) is not int or not 1024 <= port <= 65535: raise ValueError('Invalid database host port.')
        if not isinstance(password, str) or len(password) < 32: raise ValueError('A generated database password is required.')
        labels = {'io.dst.managed': 'true', 'io.dst.project': project}
        network = 'dst-' + project + '-network'
        volume = 'dst-' + project + '-postgres'
        name = 'dst-' + project + '-postgres'
        # Every name includes the private installation UUID. Conflicts fail;
        # no existing container, network or world is removed to make room.
        self.request('POST', '/networks/create', {'Name': network, 'Driver': 'bridge', 'CheckDuplicate': True, 'Labels': labels})
        self.ensure_owned_volume(volume,project,'postgres')
        container = self.request('POST', '/containers/create?name=' + name, {
            'Image': image,
            'Env': ['POSTGRES_USER=postgres', 'POSTGRES_DB=postgres', 'POSTGRES_PASSWORD=' + password],
            'Labels': {**labels, 'io.dst.component': 'postgres'},
            'ExposedPorts': {'5432/tcp': {}},
            'Healthcheck': {'Test': ['CMD-SHELL', 'pg_isready -h 127.0.0.1 -U postgres -d postgres'],
                            'Interval': 5_000_000_000, 'Timeout': 3_000_000_000, 'Retries': 10},
            'HostConfig': {'NetworkMode': network, 'RestartPolicy': {'Name': 'unless-stopped'},
                           'ShmSize': 256 * 1024 * 1024,
                           'PortBindings': {'5432/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]},
                           'Mounts': [{'Type': 'volume', 'Source': volume, 'Target': '/var/lib/postgresql/data'}],
                           'LogConfig': {'Type': 'json-file', 'Config': {'max-size': '10m', 'max-file': '3'}}}})
        identifier = container['Id']
        self.lifecycle(identifier, project, 'start')
        return {'id': identifier, 'name': name, 'network': network, 'volume': volume, 'port': port}
