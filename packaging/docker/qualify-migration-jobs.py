"""Run initial and correlated official migrations on an isolated owned cluster."""
import json
import os
from pathlib import Path
import re
import time
import uuid
import manager
from engine import Engine

project=os.environ['DST_QUALIFY_PROJECT'];port=int(os.environ['DST_QUALIFY_PORT'])
if not re.fullmatch(r'[a-f0-9]{32}',project):raise ValueError('Invalid qualification project.')
engine=Engine();state={'id':project,'phase':'new'};manager.save(state)
manager.provision_database(state,engine,port)
deadline=time.monotonic()+120
while engine.assert_owned(state['database']['id'],project,'postgres')['State'].get('Health',{}).get('Status')!='healthy':
    if time.monotonic()>deadline:raise RuntimeError('The existing qualification database is still starting; inspect its project handle.')
    time.sleep(.5)
manager.initialize_database(state,engine)
manager.migrate_database(state,engine);initial=state['migration']['id']
def wait(identifier):
    deadline=time.monotonic()+300
    while True:
        observed=engine.assert_owned(identifier,project,'db-migrate')
        if observed['State']['Status']=='exited':
            assert observed['State']['ExitCode']==0
            return
        if time.monotonic()>deadline:raise RuntimeError('The existing migration is still active; inspect its job handle.')
        time.sleep(.5)
wait(initial);manager.public_state(state,engine);assert state['phase']=='database-ready'
report=engine.backup_report(initial,project,'db-migrate');assert report['backupVerified'] and not report['roleElevated']
command=['psql','-X','-U','postgres','-d','dune','-t','-A','-v','ON_ERROR_STOP=1','-c']
def scalar(sql):return engine.exec_internal(state['database']['id'],project,'postgres',command+[sql]).strip()
before=int(scalar("SELECT count(*) FROM information_schema.tables WHERE table_schema='dune' AND table_type='BASE TABLE'"));assert before>0
assert scalar("SELECT rolsuper FROM pg_roles WHERE rolname='dune'")=='f'
assets=manager.assets_state();image=next(tag for item in assets['images'] if item['archive']=='battlegroup/server-db-utils.tar' for tag in item['tags'])
own=engine.inspect(os.environ['HOSTNAME']);volume=next(m['Name'] for m in own['Mounts'] if m['Destination']=='/projects')
operation=uuid.uuid4().hex;script=Path('/opt/dst-manager/migration-job.py').read_text();name='qualification-pre-update-'+operation[:8]+'.dump'
args=(project,image,state['database']['network'],volume,state['database']['name'],script,'dst-'+project+'-backups',name)
job=engine.create_migration_job(*args,operation=operation)
assert engine.create_migration_job(*args,operation=operation)==job
engine.lifecycle(job,project,'start');wait(job)
result=engine.backup_report(job,project,'db-migrate')
assert result['operationId']==operation and result['exitCode']==0 and result['backupVerified'] and not result['roleElevated']
assert scalar("SELECT rolsuper FROM pg_roles WHERE rolname='dune'")=='f'
after=int(scalar("SELECT count(*) FROM information_schema.tables WHERE table_schema='dune' AND table_type='BASE TABLE'"));assert after==before
for identifier in (initial,job):
    engine.assert_owned(identifier,project,'db-migrate');engine.request('DELETE','/containers/'+identifier,expected=(204,))
engine.lifecycle(state['database']['id'],project,'stop');engine.assert_owned(state['database']['id'],project,'postgres')
engine.request('DELETE','/containers/'+state['database']['id'],expected=(204,))
for name in ('dst-'+project+'-postgres','dst-'+project+'-backups'):
    assert engine.request('GET','/volumes/'+name)['Labels']['io.dst.project']==project
    engine.request('DELETE','/volumes/'+name,expected=(204,))
network=state['database']['network'];assert engine.request('GET','/networks/'+network)['Labels']['io.dst.project']==project
engine.request('DELETE','/networks/'+network,expected=(204,))
print(json.dumps({'realOfficialInitialMigration':True,'realOfficialRepeatedMigration':True,'correlatedJobReused':True,
                  'operationReportMatched':True,'applicationRoleNotSuperuser':True,'schemaTables':after,'databaseAndJobsRemoved':True}))
