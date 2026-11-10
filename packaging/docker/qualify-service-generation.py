"""Real Docker replacement/recovery using inert games and owned fixture storage."""
import copy
import io
import json
import os
from pathlib import Path
import re
import tarfile
from urllib.parse import quote
from assets import package_inventory
from engine import Engine,EngineConnection,EngineError
from game_plan import plan_world
from service_generations import replace_generation,rollback_generation
from world_template import read_template

project=os.environ['DST_QUALIFY_PROJECT']
if not re.fullmatch(r'[a-f0-9]{32}',project):raise ValueError('Invalid qualification identity.')
network='dst-'+project+'-network';saved='dst-'+project+'-game-1-saved'
profile={'name':'Generation qualification','region':'North America','address':'127.0.0.1','gamePortBase':44777}
plan=plan_world(project,profile,read_template(),{'images':package_inventory(Path('/assets/server'))},
                {'name':'dst-'+project+'-postgres','network':network,'port':18932})

class NativeEngine(Engine):
    lose_reply=False
    def create_component(self,*args,**kwargs):
        identifier=super().create_component(*args,**kwargs)
        if self.lose_reply:
            self.lose_reply=False
            raise EngineError('Qualification: Docker created the container but its response was lost.')
        return identifier

engine=NativeEngine()
if engine.request('GET','/networks/'+network,expected=(200,404)):
    raise ValueError('Qualification namespace is already occupied.')
engine.request('POST','/networks/create',{'Name':network,'Driver':'bridge','Labels':{'io.dst.managed':'true','io.dst.project':project}})
image=plan['images']['game'];engine.ensure_package_image(image['archive'],image['image'])
base={'environment':{},'entrypoint':['/bin/sh'],'command':['-c','exit 0'],'memory':64*1024**2,'map_name':'Survival_1',
      'volumes':[{'name':saved,'target':'/home/dune/server/DuneSandbox/Saved','mustBeNew':True}]}
original=engine.create_component(project,'game-1',image['image'],network,**base)
sentinel=b'Persistent qualification Saved data\n'
engine.upload_component_files(original,project,'game-1',{'home/dune/server/DuneSandbox/Saved/dst-qualification.txt':{'data':sentinel}})
state={'id':project,'profile':profile,'worldPlan':plan,'connections':{},'services':{'game-1':{'id':original,'phase':'prepared'}}}
def persist(value):Path('/fixture/generation-state.json').write_text(json.dumps(value))
def read_saved(identifier):
    engine.assert_owned(identifier,project,'game-1');connection=EngineConnection()
    try:
        connection.request('GET','/containers/'+identifier+'/archive?path='+quote('/home/dune/server/DuneSandbox/Saved/dst-qualification.txt',safe=''))
        response=connection.getresponse();raw=response.read(65537)
        if response.status!=200 or len(raw)>65536:raise ValueError('Fixture Saved read failed.')
    finally:connection.close()
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members=archive.getmembers()
        if len(members)!=1 or not members[0].isfile():raise ValueError('Invalid fixture file response.')
        return archive.extractfile(members[0]).read()
spec=copy.deepcopy(base);spec['volumes'][0]['mustBeNew']=False;spec['files']={}
replace_generation(state,engine,{'game-1':spec},plan,persist,'qualification')
new=state['services']['game-1']['id'];assert new!=original;assert read_saved(new)==sentinel
rollback_generation(state,engine,persist);assert state['services']['game-1']['id']==original
assert read_saved(original)==sentinel
engine.lose_reply=True
try:replace_generation(state,engine,{'game-1':spec},plan,persist,'qualification-lost-reply')
except EngineError:pass
else:raise ValueError('The expected lost-response fixture did not execute.')
assert 'id' not in state['services']['game-1']
rollback_generation(state,engine,persist);assert state['services']['game-1']['id']==original
assert read_saved(original)==sentinel
assert engine.assert_owned(original,project,'game-1')['Name']=='/dst-'+project+'-game-1'
filters=quote(json.dumps({'label':['io.dst.project='+project,'io.dst.managed=true']}),safe='')
containers=engine.request('GET','/containers/json?all=1&filters='+filters)
for row in containers:
    observed=engine.assert_owned(row['Id'],project,'game-1')
    assert observed['State']['Status'] in {'created','exited'}
    engine.request('DELETE','/containers/'+row['Id'],expected=(204,))
labels=engine.request('GET','/volumes/'+saved)['Labels'];assert labels['io.dst.project']==project
engine.request('DELETE','/volumes/'+saved,expected=(204,))
assert engine.request('GET','/networks/'+network)['Labels']['io.dst.project']==project
engine.request('DELETE','/networks/'+network,expected=(204,))
print(json.dumps({'realDockerReplacement':True,'savedDataPreserved':True,'originalContainerRestored':True,
                  'lostCreateResponseRecovered':True,'retainedGenerationContainers':len(containers),'qualificationResourcesRemoved':True}))
