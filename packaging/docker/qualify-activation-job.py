"""Exercise the restricted activation-job factory against disposable storage."""
import importlib.util
import json
import os
from pathlib import Path
import re
import time
import uuid
from engine import Engine

project=os.environ['DST_QUALIFY_PROJECT'];volume=os.environ['DST_QUALIFY_VOLUME']
if not re.fullmatch(r'[a-f0-9]{32}',project) or not volume.startswith('dst-qualify-activation-job-'):
    raise ValueError('Invalid qualification scope.')
module=importlib.util.spec_from_file_location('fixture','/test-fixture.py');fixture=importlib.util.module_from_spec(module);module.loader.exec_module(fixture)
original=fixture.fixture(Path('/fixture'))

class QualificationEngine(Engine):
    def request(self,method,path,body=None,expected=(200,201,204),timeout=30):
        if path=='/images/dst-docker-manager%3Alocal/json':path='/images/dst-docker-manager-qualification%3Alocal/json'
        return super().request(method,path,body,expected,timeout)

engine=QualificationEngine();jobs=[]
for mode,phase in [('activate','active'),('rollback','rolled-back')]:
    identifier=engine.create_asset_activation_job(project,uuid.uuid4().hex,fixture.STAGE,'121',mode,volume);jobs.append(identifier)
    observed=engine.assert_owned(identifier,project,'asset-switch')
    assert observed['Config']['User']=='10001:10001'
    assert observed['HostConfig']['NetworkMode']=='none' and observed['HostConfig']['ReadonlyRootfs']
    assert observed['HostConfig']['CapDrop']==['ALL']
    assert len(observed['Mounts'])==1 and observed['Mounts'][0]['Name']==volume
    engine.lifecycle(identifier,project,'start');deadline=time.monotonic()+60
    while True:
        observed=engine.assert_owned(identifier,project,'asset-switch')
        if observed['State']['Status']=='exited':break
        if time.monotonic()>deadline:raise RuntimeError('The existing qualification job is still running; inspect its recorded identity.')
        time.sleep(.2)
    assert observed['State']['ExitCode']==0
    journal=json.loads((Path('/fixture/staged')/fixture.STAGE/'activation-state.json').read_text())
    assert journal['phase']==phase
assert (Path('/fixture')/'install-state.json').read_bytes()==original
for identifier in jobs:
    observed=engine.assert_owned(identifier,project,'asset-switch');assert observed['State']['Status']=='exited'
    engine.request('DELETE','/containers/'+identifier,expected=(204,))
print(json.dumps({'restrictedJobsExecuted':2,'activated':True,'rolledBack':True,'metadataRestored':True,'uid':10001,
                  'noNetwork':True,'noProjectOrSaveMounts':True,'readOnlyRootfs':True,'allCapabilitiesDropped':True,'jobContainersRemoved':True}))
