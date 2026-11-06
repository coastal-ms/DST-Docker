"""Full stopped-world transaction on a disposable cluster and copied package."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
from urllib.parse import quote
import manager
from engine import Engine
from core_services import service_specs,game_spec
from connection_services import queue_spec
from game_plan import plan_world
from world_template import read_template
from world_update import NativeUpdate

project=os.environ['DST_QUALIFY_PROJECT']
if not re.fullmatch(r'[a-f0-9]{32}',project):raise ValueError('Invalid qualification project.')
source=json.loads(Path('/fixture-input.json').read_text())
class QualificationEngine(Engine):
    def request(self,method,path,body=None,expected=(200,201,204),timeout=30):
        if path=='/images/dst-docker-manager%3Alocal/json':path='/images/dst-docker-manager-qualification%3Alocal/json'
        return super().request(method,path,body,expected,timeout)
engine=QualificationEngine();state={'id':project,'phase':'new','memoryBalancingEnabled':False}
manager.save(state)
manager.provision_database(state,engine,int(os.environ['DST_QUALIFY_PORT']))
deadline=time.monotonic()+120
while engine.assert_owned(state['database']['id'],project,'postgres')['State'].get('Health',{}).get('Status')!='healthy':
    if time.monotonic()>deadline:raise RuntimeError('Qualification database remains starting; inspect the existing project.')
    time.sleep(.5)
manager.initialize_database(state,engine);manager.migrate_database(state,engine)
job=state['migration']['id']
while engine.assert_owned(job,project,'db-migrate')['State']['Status']!='exited':time.sleep(.5)
manager.public_state(state,engine);assert state['phase']=='database-ready'
backup_id=uuid.uuid4().hex;state['backups']={backup_id:source['backup']};state['desiredState']='stopped'
manager.restore_backup(state,engine,backup_id,'RESTORE')
template=read_template();state.update(profile={'name':'Update qualification','region':'North America','address':'127.0.0.1','gamePortBase':int(os.environ['DST_QUALIFY_BASE'])},
    partitionsPrepared=True,partitionPlan={'sha256':template['sha256'],'rows':template['partitions']},mapMemoryOverrides={'Survival_1':16*1024**3})
plan=plan_world(project,state['profile'],template,manager.assets_state(),state['database'],state['mapMemoryOverrides']);state['worldPlan']=plan
payload=base64.urlsafe_b64encode(json.dumps({'HostId':project}).encode()).decode().rstrip('=')
manager.atomic(manager.STATE/'funcom-token','qualification.'+payload+'.not-a-real-token')
credentials=manager.read_credentials(state)
specs={name:queue_spec(name,plan,template,credentials['tls']) for name in ('rmq-admin','rmq-game')}
specs.update(service_specs(plan,template,credentials))
bridge=engine.request('GET','/networks/'+plan['network'])['IPAM']['Config'][0]['Gateway']
defaults={name:(Path('/assets/server/scripts/setup/config')/name).read_text() for name in ['UserEngine.ini','UserGame.ini','UserServerCustomSettings.ini']}
for row in plan['maps']:
    for partition in row['partitions'][:row['initialReplicas']]:specs['game-'+str(partition)]=game_spec(plan,partition,credentials,bridge,defaults)
for name,spec in specs.items():
    image=plan['images']['game' if name.startswith('game-') else name];engine.ensure_package_image(image['archive'],image['image'])
    files=spec.pop('files');identifier=engine.create_component(project,name,image['image'],plan['network'],**spec)
    engine.upload_component_files(identifier,project,name,files)
    state.setdefault('connections' if name.startswith('rmq-') else 'services',{})[name]={'id':identifier,'phase':'prepared'}
saved_prefix='home/dune/server/DuneSandbox/Saved/UserSettings/'
engine.upload_component_files(state['services']['game-1']['id'],project,'game-1',{
    saved_prefix+name:{'data':raw,'uid':1000,'gid':1000,'mode':0o600} for name,raw in source['settings'].items()})
state['assetUpdate']=copy.deepcopy(source['stage']);state['assetUpdate'].pop('job',None)
state['operation']={'id':uuid.uuid4().hex,'action':'updates.apply','phase':'running'};manager.save(state)
controller=NativeUpdate(state,engine,manager)
def data_hash():return controller.sql("SELECT md5(coalesce(string_agg(row_to_json(p)::text,E'\\n' ORDER BY row_to_json(p)::text),'')) FROM dune.player_state p")
before=data_hash();original_ids={name:entry['id'] for name,entry in state['services'].items()}
result=controller.apply(source['stage']['expectedBuild'])
assert result['updated'] and not result['running'] and state['updateRun']['phase']=='completed'
assert data_hash()==before and int(controller.sql('SELECT count(*) FROM dune.player_state'))>0
assert controller.sql("SELECT rolsuper FROM pg_roles WHERE rolname='dune'")=='f'
assert all(entry['id']!=original_ids[name] for name,entry in state['services'].items())
assert engine.assert_owned(state['services']['game-1']['id'],project,'game-1')['HostConfig']['Memory']==16*1024**3
# Read bytes through Docker's archive API; no game process is started.
saved_prefix='home/dune/server/DuneSandbox/Saved/UserSettings/'
import io,tarfile
from engine import EngineConnection
for name,raw in source['settings'].items():
    connection=EngineConnection()
    try:
        connection.request('GET','/containers/'+state['services']['game-1']['id']+'/archive?path='+quote('/'+saved_prefix+name,safe=''))
        response=connection.getresponse();assert response.status==200;content=response.read(2*1024**2)
    finally:connection.close()
    with tarfile.open(fileobj=io.BytesIO(content)) as archive:assert archive.extractfile(archive.getmembers()[0]).read()==raw.encode()
proof={'fullNativeStoppedWorldUpdate':True,'copiedPlayerRowsUnchanged':True,'userIniBytesUnchanged':True,'hagga16GiBPreserved':True,
       'officialMigrationAndVerifiedBackup':True,'componentsReplaced':len(state['services'])+len(state['connections']),
       'noGameOrGatewayStarted':True,'applicationRoleNotSuperuser':True,'phase':state['updateRun']['phase']}
Path('/projects/qualification-result.json').write_text(json.dumps(proof))
print(json.dumps(proof),flush=True)
