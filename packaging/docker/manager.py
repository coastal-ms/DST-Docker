"""Local typed control plane. Own project resources only; no generic exec API."""
import json
import os
from pathlib import Path
import secrets
import socketserver
import threading
import time
import uuid
import base64
import re
import hashlib
import ipaddress
import string
import socket
import struct
from datetime import datetime
from core_services import service_specs, game_spec
from engine import Engine, EngineError
from world_template import read_template, validate_profile, fresh_partition_sql
from game_plan import plan_world, public_plan
from connection_services import ensure_tls, queue_spec
from rmq_commands import publish as publish_commands, publish_courier
from rmq_chat import operate as chat_queue
from scale_protocol import snapshot as scale_snapshot,parse_patch,scale_resource,native_director_ini,desired_partitions,party_sharing_ini,classic_automatic_maps
import file_browser
import settings_adapter
import settings_client
from asset_version import installed_version
from log_export import export_logs
import asset_updates
import service_generations
import world_update
import update_progress
import resource_policy
import map_modes
import memory_swap
import memory_swap_control
import tailscale_access
import director_web
import regis_compatibility
import backup_schedule
import backup_mirror_control
import world_restart
import world_research
import sys
import shutil

STATE = Path('/projects')
CONFIG = Path('/app-config/DuneServer')
SOCKET = Path('/control/manager.sock')
LOCK = threading.Lock()
BACKUP_WORKER = None


class OperationBusyError(ValueError):pass


def atomic(path, data, mode=0o600, group=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w',encoding='utf-8') as output:
        output.write(data)
        output.flush()
        temporary.chmod(mode)
        if group is not None: os.chown(temporary, -1, group)
        os.fsync(output.fileno())
    temporary.replace(path)
    descriptor=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def project_state():
    path = STATE / 'project.json'
    if path.exists(): return json.loads(path.read_text())
    state = {'id': uuid.uuid4().hex, 'phase': 'new', 'createdAt': time.time(), 'memoryBalancingEnabled':False}
    atomic(path, json.dumps(state))
    return state


def save(state): atomic(STATE / 'project.json', json.dumps(state))


def assets_state():
    try:
        state = json.loads(Path('/assets/install-state.json').read_text())
        return {'state': state['state'], 'images': state.get('images', []), 'updatedAt': state.get('updatedAt')}
    except (FileNotFoundError, ValueError, KeyError): return {'state': 'not-installed', 'images': []}


def finished_backup_report(engine,identifier,project,component):
    try:return engine.backup_report(identifier,project,component)
    except EngineError:return {'ok':False,'error':'The backup job ended without a valid report. Existing database and backup files were preserved.'}


def observe_backup_jobs(state,engine):
    """Reconcile owned jobs; an update may call this while retaining its lock."""
    changed=False
    for entry in state.get('backups',{}).values():
        if entry['phase']=='running':
            imported=entry.get('source')=='import'
            component='db-import' if imported else 'db-backup'
            observed=engine.assert_owned(entry['job'],state['id'],component)
            if observed['State']['Status']=='exited':
                report=finished_backup_report(engine,entry['job'],state['id'],component)
                valid=observed['State'].get('ExitCode')==0 and report.get('ok') and report.get('name')==entry['name'] and report.get('mode')==('import' if imported else 'create')
                if imported:valid=valid and report.get('uploadId')==entry['uploadId'] and report.get('sha256')==entry['sha256'] and report.get('bytes')==entry['bytes']
                valid=valid and bool(re.fullmatch(r'[a-f0-9]{64}',report.get('sha256',''))) and type(report.get('bytes')) is int and report['bytes']>0
                entry.update(phase='completed' if valid else 'failed',finishedAt=time.time())
                if valid:entry.update(sha256=report['sha256'],bytes=report['bytes'])
                else:entry['error']=report.get('error','The backup job failed. Existing data was preserved.')
                changed=True
        verification=entry.get('verification')
        if verification and verification['phase']=='running':
            observed=engine.assert_owned(verification['job'],state['id'],'db-verify')
            if observed['State']['Status']=='exited':
                report=finished_backup_report(engine,verification['job'],state['id'],'db-verify')
                valid=observed['State'].get('ExitCode')==0 and report.get('ok') and report.get('name')==entry['name'] and report.get('sha256')==entry.get('sha256') and report.get('verificationDatabaseRemoved') is True
                verification.update(phase='completed' if valid else 'failed',finishedAt=time.time())
                if valid:verification['restored']=report['restored']
                else:verification['error']=report.get('error','The restore rehearsal failed. The original database was preserved.')
                changed=True
        exported=entry.get('export')
        if exported and exported['phase']=='running':
            observed=engine.assert_owned(exported['job'],state['id'],'db-export')
            if observed['State']['Status']=='exited':
                report=finished_backup_report(engine,exported['job'],state['id'],'db-export')
                valid=(observed['State'].get('ExitCode')==0 and report.get('ok') and report.get('id')==exported['id'] and
                       report.get('name')==entry['name'] and report.get('sha256')==entry.get('sha256') and report.get('bytes')==entry.get('bytes'))
                exported.update(phase='completed' if valid else 'failed',finishedAt=time.time())
                if valid:exported['download']='/api/docker/backup-exports/'+exported['id']
                else:exported['error']='Backup export failed its verification. The original backup was preserved.'
                changed=True
    if changed:save(state)


def public_state(state, engine, *, observe=True):
    job=state.get('migration')
    if observe and job and state['phase']=='database-migrating' and state.get('operation',{}).get('phase')!='running':
        observed=engine.assert_owned(job['id'],state['id'],'db-migrate')
        if observed.get('State',{}).get('Status')=='exited':
            database=state['database']
            # Recovery also demotes after a killed job where Python finally
            # could not run. No other project's role is ever reachable here.
            engine.exec_internal(database['id'],state['id'],'postgres',
                ['psql','-X','-U','postgres','-d','postgres','-v','ON_ERROR_STOP=1','-c','ALTER ROLE dune NOSUPERUSER'])
            state['phase']='database-ready' if observed['State'].get('ExitCode')==0 else 'database-migration-failed'
            save(state)
    assets = assets_state()
    database = state.get('database')
    if database:
        observed = engine.assert_owned(database['id'], state['id'], 'postgres')
        database = {key: database[key] for key in ['name','port']}
        database['instanceId']=hashlib.sha256((state['id']+'|'+state['database']['id']).encode()).hexdigest()
        database['state'] = observed.get('State', {}).get('Status', 'unknown')
        database['health'] = observed.get('State', {}).get('Health', {}).get('Status', 'unknown')
    connections=[]
    for component,entry in state.get('connections',{}).items():
        row={'component':component,'phase':entry['phase']}
        if entry.get('id'):
            observed=engine.assert_owned(entry['id'],state['id'],component)
            row.update(name=observed.get('Name',component).lstrip('/'),state=observed['State']['Status'],health=observed['State'].get('Health',{}).get('Status','unknown'))
        connections.append(row)
    services=[]
    initial={partition for item in state.get('worldPlan',{}).get('maps',[]) for partition in item['partitions'][:item['initialReplicas']]}
    for component,entry in state.get('services',{}).items():
        row={'component':component,'phase':entry['phase']}
        desired=state.get('desiredState','stopped')
        if component.startswith('game-') and desired=='running':
            desired=state.get('mapTargets',{}).get(component,'running' if int(component.removeprefix('game-')) in initial else 'stopped')
        row['desiredState']=desired
        if entry.get('id'):
            observed=engine.assert_owned(entry['id'],state['id'],component)
            row.update(name=observed.get('Name',component).lstrip('/'),state=observed['State']['Status'],exitCode=observed['State'].get('ExitCode'))
            if observed['State'].get('StartedAt'):
                row['startedAt']=datetime.fromisoformat(observed['State']['StartedAt'].replace('Z','+00:00')).timestamp()
        services.append(row)
    director=state.get('services',{}).get('director')
    if director and any(row['component'].startswith('game-') and row.get('state')=='running' for row in services):
        try:heartbeats=engine.game_heartbeats(director['id'],state['id'])
        except (EngineError,OSError):heartbeats={}
        for row in services:
            if row['component'].startswith('game-'):
                heartbeat=heartbeats.get(int(row['component'].removeprefix('game-')))
                if heartbeat and heartbeat['observedAt']>=row.get('startedAt',float('inf')) and row.get('state')=='running':
                    row['gameReady']=heartbeat['ready'];row['players']=heartbeat['players'];row['heartbeatAt']=heartbeat['observedAt']
                    if heartbeat.get('serverId'):row['gameServerId']=heartbeat['serverId']
    if observe and state.get('operation',{}).get('phase')!='running':
        observe_backup_jobs(state,engine)
        observe_backup_cleanup(state,engine)
        backup_mirror_control.observe(state,engine,save)
    backups=[]
    for identifier,entry in state.get('backups',{}).items():
        row={key:entry[key] for key in ['name','originalFilename','phase','createdAt','finishedAt','bytes','sha256','error','operationId','scheduledSlot','requestId','source','uploadId'] if key in entry}
        row['id']=identifier
        if entry.get('verification'):
            row['verification']={key:entry['verification'][key] for key in ['phase','finishedAt','restored','error'] if key in entry['verification']}
        if entry.get('export'):
            row['export']={key:entry['export'][key] for key in ('id','phase','error','download') if key in entry['export']}
        backups.append(row)
    browser = state.get('fileBrowser')
    browser_status = None
    if browser and browser.get('id'):
        observed = engine.assert_owned(browser['id'],state['id'],'file-browser')
        browser_status = {'available': observed['State']['Status']=='running',
                          'port': browser['port'], 'phase': observed['State']['Status']}
    update, changed = asset_updates.observe_stage(state, engine)
    if changed and state.get('operation',{}).get('phase')!='running': save(state)
    try: installed_build=installed_version()['installedBuild']
    except (ValueError,OSError,KeyError): installed_build=None
    return {'projectId': state['id'], 'phase': state['phase'], 'assets': assets, 'assetUpdate': update, 'installedBuild':installed_build,
            'fileBrowser': browser_status,
            'regisPending':bool(state.get('pendingRegisChange')),
            'swapPending':bool(state.get('pendingSwapChange')),
            'database': database, 'credentialsSaved': (STATE / 'funcom-token').is_file(),
            'profile':state.get('profile'), 'partitionsPrepared':bool(state.get('partitionsPrepared')),
            'connectionServices':connections,'services':services,'desiredState':state.get('desiredState','stopped'),
            'plan':public_plan(state['worldPlan']) if state.get('worldPlan') else None,
            'operation':state.get('operation'),'startupRecoveryError':state.get('startupRecoveryError'),'backups':sorted(backups,key=lambda row:row['createdAt'],reverse=True),
            'backupMirror':backup_mirror_control.snapshot(state,engine),
            'worldRestart':world_restart.snapshot(state),
            'backupCleanup':{key:state['backupCleanup'][key] for key in ('phase','error','startedAt') if key in state['backupCleanup']} if state.get('backupCleanup') else None,
            'pendingMemoryChange':state.get('pendingMemoryChange'),
            'update':{key:state['updateRun'][key] for key in ('id','phase','build','error','recoveryError','committed','startedAt','finishedAt') if key in state['updateRun']} if state.get('updateRun') else None,
            'restore':{key:state['restore'][key] for key in ['id','name','phase','startedAt','finishedAt'] if key in state['restore']} if state.get('restore') else None}


def start_backup(state,engine,backup_id=None,scheduled_resume=None):
    if state['phase']!='database-ready':raise ValueError('Prepare the game schema before creating backups.')
    for identifier,entry in state.get('backups',{}).items():
        if scheduled_resume==identifier:continue
        if entry['phase'] in {'preparing','running'} or entry.get('verification',{}).get('phase') in {'preparing','running'}:
            raise ValueError('Another backup operation is in progress or needs recovery.')
    database=state['database']
    observed=engine.assert_owned(database['id'],state['id'],'postgres')
    resume_entry=state.get('backups',{}).get(scheduled_resume,{})
    existing_status=engine.assert_owned(resume_entry['job'],state['id'],'db-backup')['State']['Status'] if resume_entry.get('job') else None
    if existing_status not in {'running','exited'} and (observed['State']['Status']!='running' or observed['State'].get('Health',{}).get('Status')!='healthy'):
        raise ValueError('The game database must already be healthy before creating a backup. No database or maps were started.')
    images=assets_state()['images']
    tags=[tag for entry in images if entry['archive']=='battlegroup/server-db-utils.tar' for tag in entry['tags']]
    if len(tags)!=1:raise ValueError('Official database tools are unavailable.')
    engine.ensure_package_image('/assets/server/images/battlegroup/server-db-utils.tar',tags[0])
    own=engine.inspect(os.environ['HOSTNAME'])
    mounts=[mount for mount in own.get('Mounts',[]) if mount.get('Destination')=='/projects' and mount.get('Type')=='volume']
    if len(mounts)!=1:raise ValueError('Private backup control storage is unavailable.')
    entries=state.setdefault('backups',{})
    if scheduled_resume:
        entry=entries.get(scheduled_resume)
        if not entry or entry.get('requestId')!=state.get('scheduledBackup',{}).get('requestId') or entry.get('phase') not in {'preparing','running'}:
            raise ValueError('The scheduled backup recovery record does not match.')
        backup_id=scheduled_resume;mode='create';record=entry
    elif backup_id is None:
        backup_id=uuid.uuid4().hex
        entry={'phase':'preparing','createdAt':time.time(),'name':'backup-'+str(int(time.time()))+'-'+secrets.token_hex(4)+'.dump'}
        if state.get('scheduledBackup',{}).get('phase')=='dispatching':
            entry['scheduledSlot']=state['scheduledBackup']['slot']
            entry['requestId']=state['scheduledBackup']['requestId']
            state['scheduledBackup'].update(phase='running',backupId=backup_id)
        if state.get('operation',{}).get('id'):entry['operationId']=state['operation']['id']
        entries[backup_id]=entry;save(state)
        mode='create';record=entry
    else:
        if not isinstance(backup_id,str) or not re.fullmatch(r'[a-f0-9]{32}',backup_id) or backup_id not in entries:
            raise ValueError('Choose an existing backup from this installation.')
        entry=entries[backup_id]
        if entry['phase']!='completed':raise ValueError('The backup is not ready for a restore rehearsal.')
        mode='verify';record={'phase':'preparing','createdAt':time.time()}
        entry['verification']=record;save(state)
    arguments=(state['id'],tags[0],database['network'],mounts[0]['Name'],
               'dst-'+state['id']+'-backups',Path('/opt/dst-manager/backup-job.py').read_text(),mode,entry['name'],entry.get('sha256'))
    identifier=engine.create_backup_job(*arguments,**({'request_id':entry['requestId']} if mode=='create' and entry.get('requestId') else {}))
    record.update(phase='running',job=identifier);save(state)
    if mode=='create' and entry.get('requestId'):
        observed=engine.assert_owned(identifier,state['id'],'db-backup')
        if observed['State']['Status']=='created':engine.lifecycle(identifier,state['id'],'start')
        elif observed['State']['Status'] not in {'running','exited'}:raise ValueError('The scheduled backup job needs review.')
    else:engine.lifecycle(identifier,state['id'],'start')
    return public_state(state,engine)


def start_backup_cleanup(state,engine,ids):
    if state.get('backupCleanup'):raise ValueError('Finish the previous backup cleanup before deleting more files.')
    if not isinstance(ids,list) or not 1<=len(ids)<=100 or any(not isinstance(value,str) for value in ids) or len(set(ids))!=len(ids):raise ValueError('Select one to100 distinct backup records.')
    protected={value.get('backupId') for value in (state.get('restore',{}),state.get('updateRun',{}),state.get('worldRestart',{}),state.get('worldResearchRecovery',{}))} | backup_mirror_control.protected_ids(state)
    protected.add(state.get('worldRestart',{}).get('freshBackupId'))
    files=[]
    for identifier in ids:
        entry=state.get('backups',{}).get(identifier)
        if not entry or entry['phase']!='completed' or identifier in protected or entry.get('verification',{}).get('phase') in {'preparing','running'} or entry.get('export',{}).get('phase') in {'preparing','running'}:
            raise ValueError('A selected backup is active, protected for recovery, or not ready for deletion.')
        files.append({'name':entry['name'],'sha256':entry['sha256']})
    # Persist before create; an ambiguous create/start never authorizes a
    # second job or an unrelated deletion. The pending record blocks restores.
    state['backupCleanup']={'id':uuid.uuid4().hex,'ids':ids,'files':files,'phase':'preparing','startedAt':time.time()};save(state)
    identifier=engine.create_backup_cleanup_job(state['id'],files,state['backupCleanup']['id'])
    state['backupCleanup'].update(job=identifier,phase='running');save(state)
    engine.lifecycle(identifier,state['id'],'start')


def observe_backup_cleanup(state,engine):
    record=state.get('backupCleanup')
    if not record:return
    if not record.get('job'):
        raise ValueError('Interrupted backup cleanup needs review; no replacement job was issued.')
    observed=engine.assert_owned(record['job'],state['id'],'db-files')
    if observed['State']['Status']!='exited':return
    report=finished_backup_report(engine,record['job'],state['id'],'db-files')
    expected=[row['name'] for row in record['files']]
    if observed['State'].get('ExitCode')!=0 or not report.get('ok') or report.get('deleted')!=expected:
        record.update(phase='failed',error='Backup cleanup needs review. No additional files were removed.');save(state)
        return
    for identifier in record['ids']:
        state['backups'][identifier].update(phase='deleted',deletedAt=time.time())
    state['lastBackupCleanup']={**record,'phase':'completed','finishedAt':time.time()}
    state.pop('backupCleanup');save(state)


def recover_backup_cleanup(state,engine):
    record=state.get('backupCleanup')
    if not record:raise ValueError('There is no pending backup cleanup.')
    if record.get('job'):
        observed=engine.assert_owned(record['job'],state['id'],'db-files')
        if observed['State']['Status']=='running':return
        if observed['State']['Status']=='exited':
            observe_backup_cleanup(state,engine)
            if not state.get('backupCleanup'):return
            record['previousJob']=record.pop('job');record['id']=uuid.uuid4().hex
        elif observed['State']['Status']!='created':raise ValueError('The pending cleanup container needs review.')
    identifier=engine.create_backup_cleanup_job(state['id'],record['files'],record['id'])
    record.update(job=identifier,phase='running');record.pop('error',None);save(state)
    engine.lifecycle(identifier,state['id'],'start')


def start_backup_export(state,engine,backup_id):
    entry=state.get('backups',{}).get(backup_id) if isinstance(backup_id,str) else None
    if not entry or entry['phase']!='completed':raise ValueError('Choose a completed backup to download.')
    if state.get('backupCleanup'):raise ValueError('Finish pending backup cleanup before preparing a download.')
    directory=Path('/control/backup-exports')
    if directory.is_symlink():raise ValueError('Private backup export storage needs review.')
    directory.mkdir(mode=0o750,parents=True,exist_ok=True);directory.chmod(0o750);os.chown(directory,-1,10001)
    if shutil.disk_usage(directory).free<entry['bytes']+512*1024**2:raise ValueError('Backup export needs space for a temporary copy plus512 MiB free.')
    active={row['export']['id'] for row in state.get('backups',{}).values() if row.get('export',{}).get('phase') in {'preparing','running'}}
    previous=sorted((path for path in directory.glob('*.dump') if re.fullmatch(r'[a-f0-9]{32}',path.stem) and not path.is_symlink() and path.stem not in active),key=lambda path:path.stat().st_mtime,reverse=True)
    for old in previous[2:]:old.unlink()
    record=entry.get('export')
    if not record or record['phase'] not in {'preparing','running'}:
        record={'id':uuid.uuid4().hex,'phase':'preparing','startedAt':time.time()};entry['export']=record;save(state)
    request={'id':record['id'],'name':entry['name'],'sha256':entry['sha256'],'bytes':entry['bytes']}
    identifier=engine.create_backup_export_job(state['id'],request)
    record.update(job=identifier,phase='running');save(state)
    observed=engine.assert_owned(identifier,state['id'],'db-export')
    if observed['State']['Status']=='created':engine.lifecycle(identifier,state['id'],'start')
    elif observed['State']['Status'] not in {'running','exited'}:raise ValueError('The backup export container needs review.')


def start_backup_import(state,engine,request):
    upload=request.get('uploadId')
    original_filename=request.get('originalFilename','')
    if (not isinstance(original_filename,str) or len(original_filename)>255 or original_filename in {'.','..'} or
        any(ord(c)<32 or ord(c)==127 or c in '/\\' for c in original_filename)):
        raise ValueError('Choose a backup filename without a folder path or control characters.')
    if (request.get('trustedSource') is not True or not isinstance(upload,str) or not re.fullmatch(r'[a-f0-9]{32}',upload) or
        not isinstance(request.get('sha256'),str) or not re.fullmatch(r'[a-f0-9]{64}',request['sha256']) or
        type(request.get('bytes')) is not int or not 5<=request['bytes']<=25*1024**3):
        raise ValueError('Confirm the trusted source and supply a bounded PostgreSQL custom backup upload.')
    if state.get('backupCleanup'):raise ValueError('Finish pending backup cleanup before importing another backup.')
    entries=state.setdefault('backups',{})
    entry=entries.get(upload)
    if entry:
        if entry.get('source')!='import' or entry.get('uploadId')!=upload or entry.get('sha256')!=request['sha256'] or entry.get('bytes')!=request['bytes'] or entry.get('originalFilename','')!=original_filename:
            raise ValueError('The existing import does not match this upload.')
        if entry['phase']=='deleted':raise ValueError('This import was deleted. Select the backup again for a new upload.')
        if entry['phase'] in {'completed','failed'}:return
    elif any(row.get('phase') in {'preparing','running'} or row.get('verification',{}).get('phase') in {'preparing','running'} for row in entries.values()):
        raise ValueError('Wait for the active backup or restore rehearsal before importing another backup.')
    tags=[tag for item in assets_state()['images'] if item['archive']=='battlegroup/server-db-utils.tar' for tag in item['tags']]
    if len(tags)!=1:raise ValueError('Official database tools are unavailable.')
    engine.ensure_package_image('/assets/server/images/battlegroup/server-db-utils.tar',tags[0])
    if entry is None:
        entry={'source':'import','uploadId':upload,'sha256':request['sha256'],'bytes':request['bytes'],
               'phase':'preparing','createdAt':time.time(),'name':'backup-'+str(int(time.time()))+'-'+secrets.token_hex(4)+'.dump'}
        if original_filename:entry['originalFilename']=original_filename
        entries[upload]=entry;save(state)
    payload={key:entry[key] for key in ('uploadId','name','sha256','bytes')}
    identifier=engine.create_backup_import_job(state['id'],tags[0],payload,Path('/opt/dst-manager/backup_import.py').read_text())
    entry.update(phase='running',job=identifier);save(state)
    observed=engine.assert_owned(identifier,state['id'],'db-import')
    if observed['State']['Status']=='created':engine.lifecycle(identifier,state['id'],'start')
    elif observed['State']['Status'] not in {'running','exited'}:raise ValueError('The import container needs review.')


def protected_backup_jobs(state):
    protected={state.get('restore',{}).get('job'),state.get('backupCleanup',{}).get('job')}
    for entry in state.get('backups',{}).values():
        if entry.get('phase') in {'preparing','running'}:protected.add(entry.get('job'))
        if entry.get('verification',{}).get('phase') in {'preparing','running'}:protected.add(entry['verification'].get('job'))
        if entry.get('export',{}).get('phase') in {'preparing','running'}:protected.add(entry['export'].get('job'))
    mirror=state.get('backupMirror',{}).get('run',{})
    if mirror.get('phase') in {'preparing','running','failed'}:protected.add(mirror.get('job'))
    for key in ('worldRestart','worldResearchRecovery'):
        run=state.get(key,{})
        if run.get('phase','done') not in world_restart.TERMINAL|{'completed','rolled-back'}:
            protected.update(run.get(field) for field in ('freshJob','job'))
    return protected


def prune_backup_jobs(state,engine,keep_last,keep_days):
    if type(keep_last) is not int or not 0<=keep_last<=100 or type(keep_days) is not int or not 0<=keep_days<=365:
        raise ValueError('Choose job retention from zero to100 jobs and zero to365 days.')
    observe_backup_jobs(state,engine)
    protected=protected_backup_jobs(state)
    jobs=engine.backup_jobs(state['id']);terminal=[row for row in jobs if row['state']=='exited']
    deleted=[];kept=[];now=time.time()
    for index,job in enumerate(terminal):
        expired=(keep_last>0 and index>=keep_last) or (keep_days>0 and now-job['createdAt']>keep_days*86400)
        if expired and job['id'] not in protected:
            engine.remove_backup_job(state['id'],job);deleted.append(job)
        else:kept.append(job)
    return {'ok':True,'deleted':deleted,'kept':kept,'total':len(jobs)}


def backup_schedule_tick(engine=None,now=None):
    engine=engine or Engine();now=time.time() if now is None else now
    with LOCK:
        state=project_state()
        if state.get('operation',{}).get('phase')=='running':return
        observe_backup_jobs(state,engine)
        observe_backup_cleanup(state,engine)
        backup_mirror_control.tick(state,engine,save)
        for entry in state.get('backups',{}).values():
            if entry.get('source')=='import' and entry.get('phase') in {'preparing','running'}:
                if entry['phase']=='preparing' or engine.assert_owned(entry['job'],state['id'],'db-import')['State']['Status']=='created':
                    start_backup_import(state,engine,{**{key:entry[key] for key in ('uploadId','sha256','bytes')},'trustedSource':True,'originalFilename':entry.get('originalFilename','')})
        config=backup_schedule.settings(state)
        run=state.get('scheduledBackup',{})
        if run.get('phase') in {'dispatching','running'}:
            entry=state.get('backups',{}).get(run.get('backupId'))
            if not entry:
                # May be a crash before or after job creation. Do not guess
                # that the request was never dispatched and duplicate it.
                run.update(phase='review-required',error='Interrupted scheduled backup needs review before another dispatch.');save(state);return
            if entry['phase']=='preparing' or (entry['phase']=='running' and engine.assert_owned(entry['job'],state['id'],'db-backup')['State']['Status']=='created'):
                start_backup(state,engine,scheduled_resume=run['backupId']);return
            if entry['phase']=='completed':
                run.update(phase='completed',finishedAt=entry.get('finishedAt',now));save(state)
                ids=backup_schedule.retained_ids(state,config['keepLast'])[:100]
                if ids and not state.get('backupCleanup'):start_backup_cleanup(state,engine,ids)
            elif entry['phase']=='failed':
                run.update(phase='failed',error=entry.get('error','Backup failed.'),finishedAt=now);save(state)
            return
        if run.get('phase')=='review-required' or state.get('backupCleanup'):return
        if run.get('phase')=='completed' and config['preset']!='Off':
            ids=backup_schedule.retained_ids(state,config['keepLast'])[:100]
            if ids:start_backup_cleanup(state,engine,ids);return
            prune_backup_jobs(state,engine,config['keepLastPods'],config['keepDaysPods'])
        at=backup_schedule.due(state,now)
        if at is None:return
        # Defer while maintenance/another backup is active. Never start a
        # stopped database or any game to satisfy a timer.
        if state.get('phase')!='database-ready' or state.get('restore',{}).get('phase') in {'stopping','preparing','restoring','recovering','recovery-required'} or state.get('updateRun',{}).get('phase','completed') not in world_update.TERMINAL:return
        if state.get('worldRestart',{}).get('phase','done') not in world_restart.TERMINAL:return
        if state.get('worldResearchRecovery',{}).get('phase','completed') not in {'completed','rolled-back','failed-preflight'}:return
        if any(state.get(key) for key in ('pendingMemoryChange','pendingResourceChange','pendingRegisChange','pendingAddressChange')):return
        if any(row.get('phase') in {'preparing','running'} or row.get('verification',{}).get('phase') in {'preparing','running'} for row in state.get('backups',{}).values()):return
        database=state.get('database',{})
        if not database.get('id'):return
        observed=engine.assert_owned(database['id'],state['id'],'postgres')
        if observed['State']['Status']!='running' or observed['State'].get('Health',{}).get('Status')!='healthy':return
        state['scheduledBackup']={'slot':at,'phase':'dispatching','requestId':uuid.uuid4().hex,'startedAt':now};save(state)
        start_backup(state,engine)


def run_backup_scheduler():
    while True:
        try:backup_schedule_tick()
        except Exception:
            # Keep failures observable without taking down the control socket.
            with LOCK:
                state=project_state()
                if state.get('operation',{}).get('phase')!='running':
                    state['backupSchedulerError']='Automatic backup needs review. Existing database and backup records were retained.';save(state)
        time.sleep(30)


def recover_scheduled_backup(state,engine):
    run=state.get('scheduledBackup',{})
    if run.get('phase') not in {'review-required','dispatching','running'} or not re.fullmatch(r'[a-f0-9]{32}',str(run.get('requestId',''))):
        raise ValueError('There is no identified interrupted scheduled backup to resume.')
    if run.get('backupId') in state.get('backups',{}):
        start_backup(state,engine,scheduled_resume=run['backupId']);run.pop('error',None);return
    expected='dst-'+state['id']+'-db-backup-'+run['requestId']
    jobs=[row for row in engine.backup_jobs(state['id']) if row['name']==expected and row['component']=='db-backup']
    if len(jobs)>1:raise ValueError('More than one helper matches the recorded backup identity; review is required.')
    if jobs:
        observed=engine.assert_owned(jobs[0]['id'],state['id'],'db-backup')
        values=dict(value.split('=',1) for value in observed.get('Config',{}).get('Env',[]) if '=' in value)
        name=values.get('DST_BACKUP_NAME','')
        if values.get('DST_BACKUP_MODE')!='create' or not re.fullmatch(r'backup-[0-9]+-[a-f0-9]{8}\.dump',name):raise ValueError('The existing helper does not match the saved backup operation.')
        identifier=uuid.uuid4().hex
        state.setdefault('backups',{})[identifier]={'phase':'preparing','name':name,'createdAt':jobs[0]['createdAt'],
            'scheduledSlot':run['slot'],'requestId':run['requestId'],'job':jobs[0]['id']}
        run.update(phase='running',backupId=identifier);run.pop('error',None);save(state)
        start_backup(state,engine,scheduled_resume=identifier)
    else:
        # A deterministic Docker job name also guards a late create response.
        # Its factory adopts a matching existing job, or rejects any mismatch.
        run.update(phase='dispatching');run.pop('error',None);save(state)
        start_backup(state,engine)


def restore_backup(state,engine,backup_id,confirmation,keep_maintenance=False):
    if confirmation!='RESTORE':raise ValueError('Type RESTORE to confirm the selected database replacement.')
    if state['phase']!='database-ready':raise ValueError('The game database is not ready.')
    if not isinstance(backup_id,str) or not re.fullmatch(r'[a-f0-9]{32}',backup_id):raise ValueError('Choose a saved backup.')
    backup=state.get('backups',{}).get(backup_id)
    if not backup or backup['phase']!='completed' or backup.get('verification',{}).get('phase')!='completed':
        raise ValueError('Verify the selected backup before restoring it.')
    counts=backup['verification'].get('restored',{})
    if set(counts)!={'duneTables','duneViews','partitions','players'}:raise ValueError('Run Verify restore again to refresh this backup record.')
    for entry in state.get('backups',{}).values():
        if entry['phase'] in {'preparing','running'} or entry.get('verification',{}).get('phase') in {'preparing','running'}:
            raise ValueError('Wait for the current backup operation to finish.')
    image=next(tag for entry in assets_state()['images'] if entry['archive']=='battlegroup/server-db-utils.tar' for tag in entry['tags'])
    own=engine.inspect(os.environ['HOSTNAME'])
    volume=next(mount['Name'] for mount in own['Mounts'] if mount.get('Destination')=='/projects' and mount.get('Type')=='volume')
    operation=uuid.uuid4().hex;resume=state.get('desiredState')=='running'
    before='backup-'+str(int(time.time()))+'-'+secrets.token_hex(4)+'.dump'
    record={'id':operation,'backupId':backup_id,'name':backup['name'],'phase':'stopping','resume':resume,'startedAt':time.time(),
            'beforeName':before,'image':image,'stateVolume':volume,'keepMaintenance':keep_maintenance}
    state['restore']=record;save(state)
    atomic(CONFIG/'docker-maintenance.json',json.dumps({'active':True,'operation':operation}),0o640,10001)
    try:stop_services(state,engine)
    except Exception:
        record['phase']='failed';save(state)
        if not keep_maintenance:atomic(CONFIG/'docker-maintenance.json',json.dumps({'active':False,'operation':operation}),0o640,10001)
        raise
    record['phase']='preparing';save(state)
    identifier=engine.create_restore_job(state['id'],image,state['database']['network'],volume,'dst-'+state['id']+'-backups',
        Path('/opt/dst-manager/restore-job.py').read_text(),operation,'dune',backup['name'],backup['sha256'],before,counts)
    record.update(job=identifier,phase='restoring');save(state)
    engine.lifecycle(identifier,state['id'],'start')
    return finish_restore(state,engine)


def finish_restore(state,engine):
    record=state['restore'];identifier=record['job']
    deadline=time.monotonic()+7200
    while engine.assert_owned(identifier,state['id'],'db-restore')['State']['Status']!='exited':
        if time.monotonic()>deadline:raise EngineError('The restore is still running. Check its status before another operation.')
        time.sleep(1)
    report=engine.backup_report(identifier,state['id'],'db-restore')
    if report.get('operationId')!=record['id'] or report.get('target')!='dune' or report.get('name')!=record['name']:
        raise EngineError('The restore report does not match this operation.')
    original_report=report
    if report.get('phase') not in {'completed','failed'} or report.get('recoveryRequired'):
        # An exited job may have been killed between the two database names
        # being exchanged and reopening connections. Recover by verified OID,
        # using the same operation namespace, rather than guessing by name.
        if all(type(report.get(key)) is int and report[key]>0 for key in ['originalOid','stageOid']):
            backup=state['backups'][record['backupId']]
            recovery_job=record.get('recoveryJob')
            if not recovery_job:
                recovery_job=engine.create_restore_job(state['id'],record['image'],state['database']['network'],
                    record['stateVolume'],'dst-'+state['id']+'-backups',Path('/opt/dst-manager/restore-job.py').read_text(),
                    record['id'],'dune',record['name'],backup['sha256'],record['beforeName'],
                    backup['verification']['restored'],mode='recover',recovery=report)
                record.update(recoveryJob=recovery_job,phase='recovering');save(state)
            observed=engine.assert_owned(recovery_job,state['id'],'db-restore')
            if observed['State']['Status']=='created':engine.lifecycle(recovery_job,state['id'],'start')
            while engine.assert_owned(recovery_job,state['id'],'db-restore')['State']['Status']!='exited':
                if time.monotonic()>deadline:raise EngineError('Restore recovery is still running.')
                time.sleep(1)
            recovery=engine.backup_report(recovery_job,state['id'],'db-restore')
            if recovery.get('ok') and recovery.get('phase')=='recovered' and recovery.get('operationId')==record['id']:
                report={**original_report,'ok':False,'phase':'failed','recoveryRequired':False,
                        'error':'The restore was interrupted and the previous database was reopened.',
                        'rollbackPerformed':recovery.get('rollbackPerformed',False)}
        elif report.get('originalOid') and not report.get('connectionsFenced'):
            report={**report,'ok':False,'phase':'failed','error':'The restore ended before database replacement.'}
    record.update(report=report,finishedAt=time.time())
    if report.get('phase') not in {'completed','failed'} or report.get('recoveryRequired'):
        record['phase']='recovery-required';save(state)
        raise EngineError('The restore needs recovery review before the database can be reopened.')
    if report.get('beforeBackup') and not any(entry.get('name')==report['beforeBackup']['name'] for entry in state.get('backups',{}).values()):
        entry=report['beforeBackup'];state.setdefault('backups',{})[uuid.uuid4().hex]={
            'name':entry['name'],'sha256':entry['sha256'],'bytes':entry['bytes'],'phase':'completed',
            'createdAt':record['startedAt'],'finishedAt':time.time(),'purpose':'before-restore'}
    record['phase']='completed' if report.get('ok') else 'failed';save(state)
    if not record.get('keepMaintenance'):atomic(CONFIG/'docker-maintenance.json',json.dumps({'active':False,'operation':record['id']}),0o640,10001)
    if record['resume']:start_services(state,engine)
    if not report.get('ok'):raise EngineError(report.get('error','Restore failed.'))
    return public_state(state,engine)


def resume_interrupted_restore(state,engine):
    try:
        record=state['restore']
        if record.get('job'):
            observed=engine.assert_owned(record['job'],state['id'],'db-restore')
            if observed['State']['Status']=='created':engine.lifecycle(record['job'],state['id'],'start')
            finish_restore(state,engine)
            state['operation'].update(phase='completed',finishedAt=time.time())
        else:
            # Jobs are journaled before start. Without a job no database
            # replacement has begun; finish the stop and reopen the world.
            stop_services(state,engine)
            if not record.get('keepMaintenance'):atomic(CONFIG/'docker-maintenance.json',json.dumps({'active':False,'operation':record['id']}),0o640,10001)
            record['phase']='failed';record['finishedAt']=time.time();save(state)
            if record['resume']:start_services(state,engine)
            state['operation'].update(phase='failed',error='Restore interrupted before database replacement. Start the restore again.',finishedAt=time.time())
    except (ValueError,EngineError) as error:
        state['operation'].update(phase='failed',error=str(error),finishedAt=time.time())
    except Exception:
        state['operation'].update(phase='failed',error='Restore recovery needs review.',finishedAt=time.time())
    finally:save(state)


def validate_connection_plan(state):
    if state['phase']!='database-ready' or not state.get('partitionsPrepared'):
        raise ValueError('Prepare the world database and layout first.')
    template=read_template()
    plan=plan_world(state['id'],state['profile'],template,assets_state(),state['database'],state.get('mapMemoryOverrides'),state.get('memorySwap'))
    previous=state.get('worldPlan')
    if previous:
        # Old journals predate optional swap metadata. Missing and null both
        # mean the unconfigured/default policy, not a changed connection plan.
        previous={**previous,'databaseName':state['database']['name'],'databasePort':state['database']['port'],
                  'memorySwap':previous.get('memorySwap')}
    if previous and previous!=plan:
        raise ValueError('The installed connection plan differs from these settings. Stop and review it first.')
    return template,plan


def prepare_connections(state,engine):
    template,plan=validate_connection_plan(state)
    state['worldPlan']=plan; save(state)
    tls=tls_for_plan(plan)
    tls_hash=hashlib.sha256(tls['ca.pem']+tls['cert.pem']).hexdigest()
    for component in ['rmq-admin','rmq-game']:
        entries=state.setdefault('connections',{})
        entry=entries.get(component)
        if entry:
            if not entry.get('id') or entry['phase']!='prepared':
                raise ValueError('A previous connection-service attempt needs recovery before another can start.')
            engine.assert_owned(entry['id'],state['id'],component)
            if component=='rmq-game' and entry.get('tlsSha256')!=tls_hash:
                # Only this installation's queue can be stopped or updated.
                # Preserve the previous certificate directory for recovery.
                engine.lifecycle(entry['id'],state['id'],'stop')
                entry['phase']='configuring';save(state)
                files=queue_spec(component,plan,template,tls)['files']
                engine.upload_component_files(entry['id'],state['id'],component,files)
                entry.update(phase='prepared',tlsSha256=tls_hash);save(state)
        else:
            source=plan['images'][component]
            engine.ensure_package_image(source['archive'],source['image'])
            entries[component]={'phase':'creating','createdAt':time.time()}; save(state)
            spec=queue_spec(component,plan,template,tls)
            files=spec.pop('files')
            identifier=engine.create_component(state['id'],component,source['image'],plan['network'],**spec)
            entries[component].update(id=identifier,phase='configuring'); save(state)
            engine.upload_component_files(identifier,state['id'],component,files)
            entries[component].update(phase='prepared',tlsSha256=tls_hash if component=='rmq-game' else None);save(state)
            entry=entries[component]
        observed=engine.assert_owned(entry['id'],state['id'],component)
        if observed['State']['Status'] in {'created','exited'}:
            engine.lifecycle(entry['id'],state['id'],'start')
    return public_state(state,engine)


def tls_for_plan(plan):
    hostname=plan['names']['rmq-game'];address=plan['profile']['address']
    legacy=STATE/'tls-v2'
    if (legacy/'identity').is_file() and (legacy/'identity').read_text()=='2\n'+hostname+'\n'+address:
        return ensure_tls(legacy,hostname,address)
    key=hashlib.sha256((hostname+'\n'+address).encode()).hexdigest()[:24]
    return ensure_tls(STATE/'tls-addresses'/key,hostname,address)


def read_credentials(state):
    token=(STATE/'funcom-token').read_text()
    claims=json.loads(base64.urlsafe_b64decode(token.split('.')[1]+'='*((-len(token.split('.')[1]))%4)))
    host_id=claims['HostId'].lower()
    if state.get('hostId') and state['hostId']!=host_id:
        raise ValueError('This token belongs to a different self-host identity; existing services were preserved.')
    if not state.get('worldId'):
        state.update(hostId=host_id,worldId='sh-'+host_id+'-'+''.join(secrets.choice(string.ascii_lowercase) for _ in range(6)))
        save(state)
    def secret(name,default):
        path=STATE/name
        if not path.exists(): atomic(path,default())
        return path.read_text()
    result={'token':token,'worldId':state['worldId'],'dbPassword':(STATE/'dune-app.password').read_text(),
            'apiKey':secret('gateway-api.key',lambda:str(uuid.uuid4())),
            'rmqSecret':secret('rmq-auth.secret',lambda:secrets.token_urlsafe(48)),
            'tls':tls_for_plan(state['worldPlan'])}
    if state.get('scaler',{}).get('phase')=='prepared':
        tls=ensure_tls(STATE/'scaler-tls','dst-'+state['id']+'-scaler','127.0.0.1')
        result['scaler']={'hostname':'dst-'+state['id']+'-scaler','token':(STATE/'scaler-token').read_text(),'ca':tls['ca.pem']}
    return result


def prepare_scaler(state,engine):
    if not state.get('worldPlan') or not state.get('worldId'):raise ValueError('Prepare the world services first.')
    if not (STATE/'scaler-token').exists():atomic(STATE/'scaler-token',secrets.token_urlsafe(48))
    tls=ensure_tls(STATE/'scaler-tls','dst-'+state['id']+'-scaler','127.0.0.1')
    entry=state.get('scaler')
    if not entry:
        own=engine.inspect(os.environ['HOSTNAME'])
        control=next(mount['Name'] for mount in own['Mounts'] if mount.get('Destination')=='/control' and mount.get('Type')=='volume')
        state['scaler']={'phase':'creating'};save(state)
        identifier=engine.create_scaler(state['id'],state['worldPlan']['network'],control)
        entry={'phase':'configuring','id':identifier};state['scaler']=entry;save(state)
        files={name:{'data':tls[name],'uid':0,'gid':10001,'mode':0o440} for name in ['cert.pem','key.pem']}
        files.update({'token':{'data':(STATE/'scaler-token').read_text(),'uid':0,'gid':10001,'mode':0o440},
                      'world':{'data':state['worldId'],'uid':0,'gid':10001,'mode':0o440}})
        engine.upload_component_files(identifier,state['id'],'scaler',files,destination='/etc/dst-scaler')
        entry['phase']='prepared';save(state)
    if entry.get('phase')!='prepared' or not entry.get('id'):raise ValueError('Scaler preparation needs recovery review.')
    engine.assert_owned(entry['id'],state['id'],'scaler');engine.lifecycle(entry['id'],state['id'],'start')
    return public_state(state,engine)


def refresh_core_adapters(state,engine):
    if state.get('desiredState')!='stopped':raise ValueError('Stop the world before applying the native orchestration adapter.')
    if state.get('scaler',{}).get('phase')!='prepared':raise ValueError('Prepare the native scaler first.')
    for component,entry in state.get('services',{}).items():
        observed=engine.assert_owned(entry['id'],state['id'],component)
        if observed['State']['Status'] not in {'created','exited'}:raise ValueError('Every world service must finish stopping first.')
    current=engine.read_director_config(state['services']['director']['id'],state['id']).decode()
    config=native_director_ini(current,state['worldPlan'],state.get('manualPins'),state.get('mapModes'))
    specifications=service_specs(state['worldPlan'],read_template(),read_credentials(state))
    specifications['director']['files']['Tools/Battlegroups/Director/BattlegroupDirector/director_config.ini']['data']=config
    for component in ['director','text-router']:
        entry=state['services'][component];old=entry['id'];spec=specifications[component];files=spec.pop('files')
        entry.update(phase='replacing',previousId=old);save(state)
        entry['previousName']=engine.retire_component(old,state['id'],component);save(state)
        identifier=engine.create_component(state['id'],component,state['worldPlan']['images'][component]['image'],state['worldPlan']['network'],**spec)
        entry.update(id=identifier,phase='configuring');save(state)
        engine.upload_component_files(identifier,state['id'],component,files)
        entry['phase']='prepared';save(state)
    state['scaler']['coreAdapterApplied']=True;save(state)
    return public_state(state,engine)


def prepare_services(state,engine):
    if not (STATE/'funcom-token').is_file(): raise ValueError('Save your Funcom service token first.')
    prepare_connections(state,engine)
    plan=state['worldPlan']
    credentials=read_credentials(state)
    prepare_scaler(state,engine)
    credentials=read_credentials(state)
    template=read_template()
    if not state.get('memoryBalancingEnabled', True):
        source=template['world']['spec']['utilities']['director']['spec']['configFiles']['files']['director.ini']
        state['classicAutomaticMaps']=classic_automatic_maps(source);save(state)
    specifications=service_specs(plan,template,credentials)
    specifications['director']['files']['Tools/Battlegroups/Director/BattlegroupDirector/director_config.ini']['data']=native_director_ini(
        template['world']['spec']['utilities']['director']['spec']['configFiles']['files']['director.ini'],plan,state.get('manualPins'),state.get('mapModes'))
    network=engine.request('GET','/networks/'+plan['network'])
    bridge=network['IPAM']['Config'][0]['Gateway']
    if ipaddress.ip_address(bridge).version!=4: raise ValueError('The native game network requires an IPv4 gateway.')
    initial=[]
    for item in plan['maps']:
        initial.extend(item['partitions'][:item['initialReplicas']])
    defaults={name:(Path('/assets/server/scripts/setup/config')/name).read_text()
              for name in ['UserEngine.ini','UserGame.ini','UserServerCustomSettings.ini']}
    for partition in sorted(initial):
        specifications['game-'+str(partition)]=regis_compatibility.apply_image_policy(state,partition,game_spec(plan,partition,credentials,bridge,defaults))
    for component,spec in specifications.items():
        entries=state.setdefault('services',{})
        entry=entries.get(component)
        if entry:
            if not entry.get('id') or entry['phase']!='prepared':
                raise ValueError('A previous game-service attempt needs recovery before another can start.')
            engine.assert_owned(entry['id'],state['id'],component)
            continue
        source=plan['images']['game' if component.startswith('game-') else component]
        engine.ensure_package_image(source['archive'],source['image'])
        files=spec.pop('files')
        entries[component]={'phase':'creating','createdAt':time.time()};save(state)
        identifier=engine.create_component(state['id'],component,source['image'],plan['network'],**spec)
        entries[component].update(id=identifier,phase='configuring');save(state)
        engine.upload_component_files(identifier,state['id'],component,files)
        entries[component]['phase']='prepared';save(state)
    expected='KUBERNETES_SERVICE_HOST=dst-'+state['id']+'-scaler'
    if all(expected in engine.assert_owned(state['services'][component]['id'],state['id'],component)['Config']['Env'] for component in ['director','text-router']):
        state['scaler']['coreAdapterApplied']=True;save(state)
    prepare_settings_service(state,engine)
    return public_state(state,engine)


def ensure_database_ready(state,engine,timeout=90):
    database=state.get('database',{})
    if not database.get('id') or state.get('phase')!='database-ready':
        raise ValueError('Finish database setup and migration before starting the world.')
    observed=engine.assert_owned(database['id'],state['id'],'postgres')
    status=observed['State']['Status']
    if status in {'created','exited'}:
        engine.lifecycle(database['id'],state['id'],'start')
    elif status not in {'running','restarting'}:
        raise ValueError('The existing game database cannot start in its current container state.')
    deadline=time.monotonic()+timeout
    while True:
        observed=engine.assert_owned(database['id'],state['id'],'postgres')
        status=observed['State']['Status']
        if status=='running' and observed['State'].get('Health',{}).get('Status')=='healthy':return
        if status not in {'running','restarting'}:
            raise ValueError('The existing game database stopped during startup. Check its logs; maps were not started.')
        if time.monotonic()>=deadline:
            raise ValueError('The game database did not become ready. Check its logs and retry Start Battlegroup; maps were not started.')
        time.sleep(0.25)


def stop_database_only(state,engine):
    database=state.get('database',{})
    if not database.get('id') or state.get('phase')!='database-ready':raise ValueError('Complete database setup before using database controls.')
    if state.get('desiredState','stopped')!='stopped':raise ValueError('Stop the battlegroup before stopping its database.')
    for component,entry in state.get('services',{}).items():
        if engine.assert_owned(entry['id'],state['id'],component)['State']['Status'] not in {'created','exited'}:
            raise ValueError('Every battlegroup service must be stopped before its database can stop.')
    if any(entry.get('phase') in {'preparing','running'} or entry.get('verification',{}).get('phase') in {'preparing','running'} for entry in state.get('backups',{}).values()):
        raise ValueError('Wait for backup and restore jobs before stopping the database.')
    observed=engine.assert_owned(database['id'],state['id'],'postgres')
    if observed['State']['Status'] in {'created','exited'}:return
    if observed['State']['Status'] not in {'running','restarting'}:raise ValueError('The database container needs review before stopping.')
    engine.lifecycle(database['id'],state['id'],'stop')


def start_services(state,engine,publish_gateway=True):
    if state.get('pendingSwapChange'):raise ValueError('Retry or restore the pending Memory Swap change before starting maps.')
    regis_compatibility.assert_prepared_images(state,engine)
    if state.get('pendingResourceChange'):raise ValueError('Finish the pending resource allocation before starting the world.')
    if type(publish_gateway) is not bool:raise ValueError('The gateway publication choice must be a JSON boolean.')
    if not publish_gateway and state.get('services',{}).get('gateway'):
        gateway=engine.assert_owned(state['services']['gateway']['id'],state['id'],'gateway')
        if gateway['State']['Status'] not in {'created','exited'}:
            raise ValueError('Stop the gateway before starting unpublished maps.')
    if state.get('pendingMemoryChange'):raise ValueError('Finish the pending map memory allocation before starting the world.')
    if state.get('pendingAddressChange'):raise ValueError('Finish the network configuration update before starting the world.')
    if not state.get('services') or any(entry['phase']!='prepared' for entry in state['services'].values()):
        raise ValueError('Prepare all game services before starting the world.')
    needed=0
    initial={partition for item in state['worldPlan']['maps'] for partition in item['partitions'][:item['initialReplicas']]}
    selected={int(name.removeprefix('game-')) for name in state['services'] if name.startswith('game-')
              and state.get('mapTargets',{}).get(name,'running' if int(name.removeprefix('game-')) in initial else 'stopped')=='running'}
    disabled={p for row in state['worldPlan']['maps'] if state.get('mapModes',{}).get(row['map'])=='disabled' for p in row['partitions']}
    selected-=disabled
    resource_policy.admit(state,engine,selected)
    for component,entry in state['services'].items():
        if component.startswith('game-') and int(component.removeprefix('game-')) not in selected:continue
        observed=engine.assert_owned(entry['id'],state['id'],component)
        if component.startswith('game-') and observed['State']['Status']!='running':
            partition=int(component.removeprefix('game-'))
            game=next(row for row in state['worldPlan']['games'] if row['partition']==partition)
            needed+=next(row['memoryBytes'] for row in state['worldPlan']['maps'] if row['map']==game['map'])
    if needed:
        counters={line.split(':',1)[0]:line.split(':',1)[1].strip().split()[0] for line in Path('/proc/meminfo').read_text().splitlines()}
        available=int(counters['MemAvailable'])*1024
        if available<needed+2*1024**3:
            raise ValueError(f'Starting these maps needs {needed/1024**3:.1f} GiB plus 2 GiB host headroom; {available/1024**3:.1f} GiB is available.')
    # A host reboot stops the infrastructure too. Start the existing migrated
    # database only after admission checks, and wait before launching any maps.
    # This never recreates storage, initializes roles, or reruns migrations.
    ensure_database_ready(state,engine)
    state['desiredState']='running';save(state)
    prepare_connections(state,engine)
    if state.get('scaler',{}).get('phase')=='prepared':engine.lifecycle(state['scaler']['id'],state['id'],'start')
    for component in ['text-router','director']+(['gateway'] if publish_gateway else [])+['game-'+str(partition) for partition in sorted(selected)]:
        if component.startswith('game-') and state.get('resourcePolicy'):
            game=next(row for row in state['worldPlan']['games'] if row['partition']==int(component[5:]))
            engine.set_component_cpu(state['services'][component]['id'],state['id'],component,state.get('mapCpuOverrides',{}).get(game['map']))
        engine.lifecycle(state['services'][component]['id'],state['id'],'start')
    prepare_map_observers(state,engine)
    prepare_file_browser(state,engine)
    prepare_settings_service(state,engine)
    return public_state(state,engine)


def prepare_settings_service(state,engine):
    own=engine.inspect(os.environ['HOSTNAME'])
    control=next(mount['Name'] for mount in own['Mounts'] if mount.get('Destination')=='/map-control' and mount.get('Type')=='volume')
    image=own['Image']
    entry=state.get('settingsService')
    if entry:
        previous=engine.assert_owned(entry['id'],state['id'],'settings')
        if previous.get('Image')!=image:
            engine.lifecycle(entry['id'],state['id'],'stop')
            engine.request('POST','/containers/'+entry['id']+'/rename?name=dst-'+state['id']+'-settings-previous-'+secrets.token_hex(4))
            state.pop('settingsService');save(state);entry=None
    if not entry:
        entry={'id':settings_adapter.create(state,engine,control)}
        state['settingsService']=entry;save(state)
    engine.lifecycle(entry['id'],state['id'],'start')


def settings_pending(timestamp,observed):
    if not timestamp:return False
    if not observed or observed.get('State',{}).get('Status')!='running':return True
    try:
        from datetime import datetime
        return datetime.fromisoformat(observed['State']['StartedAt'].replace('Z','+00:00')).timestamp()<=timestamp
    except (KeyError,ValueError):return True


def write_settings(state,engine,request):
    key=request.get('file')
    if not isinstance(key,str) or key not in {'game','engine','server'}:raise ValueError('Choose a supported server INI file.')
    payload={key:request.get(key) for key in ['file','raw','revision','expectedExists','remove'] if key in request}
    payload['action']='write'
    reply=settings_client.request(payload)
    if not reply.get('ok'):raise ValueError(reply.get('error','Server settings could not be saved.'))
    if reply['data'].get('changed'):
        state.setdefault('globalSettingsPending',{})[key]=time.time();save(state)
    return {**reply['data'],'restartRequired':True}


def read_settings(state,engine,key):
    if not isinstance(key,str) or key not in {'game','engine','server'}:
        raise ValueError('Choose a supported server INI file.')
    return settings_request(state,engine,{'action':'read','file':key})


def settings_request(state,engine,payload):
    # The management console remains usable with the world stopped. Only this
    # world's isolated file helper may start; never any game or database service.
    entry=state.get('settingsService')
    observed=engine.assert_owned(entry['id'],state['id'],'settings') if entry else None
    if not observed or observed['State']['Status']!='running' or observed.get('Image')!=engine.inspect(os.environ['HOSTNAME'])['Image']:
        prepare_settings_service(state,engine)
    deadline=time.monotonic()+5
    while True:
        try:
            reply=settings_client.request(payload)
            break
        except (FileNotFoundError,ConnectionRefusedError):
            if time.monotonic()>=deadline:raise ValueError('The server settings service did not become ready.') from None
            time.sleep(0.1)
    if not reply.get('ok'):raise ValueError(reply.get('error','Server settings could not be read.'))
    return reply['data']


def set_startup_settings(state,engine,values):
    if not isinstance(values,dict) or len(values)>10000:raise ValueError('Startup console variables must be a settings object.')
    commands=[]
    for key,value in sorted(values.items()):
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]{0,255}',key) or key.lower()=='bgd.serverloginpassword':
            raise ValueError('Unsupported startup console variable.')
        if value is None:continue
        if not isinstance(value,str) or len(value)>512 or re.search(r'[,"\x00-\x1f\x7f]',value):
            raise ValueError('A startup console variable cannot be encoded safely.')
        if value.strip():commands.append(key+' '+value.strip())
    current=settings_client.request({'action':'read','file':'startup'})
    if not current.get('ok'):raise ValueError(current.get('error','Startup settings could not be read.'))
    current=current['data']
    result=settings_client.request({'action':'write','file':'startup','raw':','.join(commands)+'\n' if commands else '',
                                    'revision':current['revision'],'expectedExists':current['fileExists']})
    if not result.get('ok'):raise ValueError(result.get('error','Startup settings could not be saved.'))
    return {'Success':True,'count':len(commands),'changed':result['data']['changed']}


def prepare_file_browser(state,engine):
    mounts=file_browser.saved_mounts(state,engine)
    entry=state.get('fileBrowser')
    if entry and (entry.get('mounts')!=mounts or entry.get('baseUrl')!=file_browser.BASE_URL):
        engine.lifecycle(entry['id'],state['id'],'stop')
        engine.assert_owned(entry['id'],state['id'],'file-browser')
        engine.request('POST','/containers/'+entry['id']+'/rename?name=dst-'+state['id']+'-file-browser-previous-'+secrets.token_hex(4))
        state.pop('fileBrowser');save(state);entry=None
    if not entry:
        identifier=file_browser.create(state,engine,mounts)
        entry={'id':identifier,'mounts':mounts,'port':state['profile']['gamePortBase']+1005,'baseUrl':file_browser.BASE_URL}
        state['fileBrowser']=entry;save(state)
    engine.lifecycle(entry['id'],state['id'],'start')
    deadline=time.monotonic()+12
    while True:
        observed=engine.assert_owned(entry['id'],state['id'],'file-browser')
        health=observed.get('State',{}).get('Health',{}).get('Status')
        if observed['State']['Status']=='running' and health=='healthy':break
        if observed['State']['Status'] not in {'running','created'} or time.monotonic()>=deadline:
            raise ValueError('File Browser did not become ready. Reopen it from the dashboard to retry.')
        time.sleep(0.2)


def prepare_map_observers(state,engine):
    own=engine.inspect(os.environ['HOSTNAME'])
    control=next(mount['Name'] for mount in own['Mounts'] if mount.get('Destination')=='/map-control' and mount.get('Type')=='volume')
    image=engine.request('GET','/images/dst-docker-map-observer%3Alocal/json')['Id']
    entries=state.setdefault('mapObservers',{})
    for partition in [1,8]:
        component='game-'+str(partition);game=state.get('services',{}).get(component)
        if not game or not game.get('id'):continue
        observed=engine.assert_owned(game['id'],state['id'],component)
        entry=entries.get(component)
        if observed['State']['Status']!='running':continue
        previous=engine.assert_owned(entry['id'],state['id'],'map-observer-'+str(partition)) if entry else None
        if entry and (entry.get('gameId')!=game['id'] or previous.get('Image')!=image):
            engine.remove_map_observer(entry['id'],state['id'],partition)
            del entries[component];entry=None;save(state)
        if entry:
            helper=engine.assert_owned(entry['id'],state['id'],'map-observer-'+str(partition))
            if entry.get('gameStartedAt')!=observed['State']['StartedAt'] and helper['State']['Status']=='running':
                engine.lifecycle(entry['id'],state['id'],'stop')
        else:
            identifier=engine.create_map_observer(state['id'],partition,game['id'],control)
            entry={'id':identifier,'gameId':game['id']};entries[component]=entry;save(state)
        engine.lifecycle(entry['id'],state['id'],'start')
        entry['gameStartedAt']=observed['State']['StartedAt'];save(state)
    return public_state(state,engine)


def control_map(state,engine,partition,running,force=False,automatic=False):
    if type(partition) is not int or type(running) is not bool or type(force) is not bool:raise ValueError('Choose a valid map partition.')
    if state.get('desiredState')!='running':raise ValueError('Start the battlegroup before controlling a map.')
    plan=state.get('worldPlan',{})
    game=next((row for row in plan.get('games',[]) if row['partition']==partition),None)
    if not game:raise ValueError('This partition is not in the installed world catalogue.')
    component='game-'+str(partition);entry=state.get('services',{}).get(component)
    map_info=next(row for row in plan['maps'] if row['map']==game['map'])
    if running and state.get('mapModes',{}).get(game['map'])=='disabled':
        raise ValueError('This map is disabled. Choose another mode before starting it.')
    def manual_floor():
        if not automatic:
            if map_info.get('initialReplicas',0)==0:
                if state.get('mapModes',{}).get(game['map'])!='disabled':
                    state.setdefault('mapModes',{})[game['map']]='always-on' if running else 'dynamic'
                set_map_floor(state,engine,game['map'],running)
            else:
                set_map_floor(state,engine,game['map'],running,allow_initial=True)
    if running:
        regis_compatibility.assert_prepared_images(state,engine,[component])
        observed=engine.assert_owned(entry['id'],state['id'],component) if entry and entry.get('id') else None
        if observed and observed['State']['Status']=='running':
            manual_floor()
            if not automatic:state.setdefault('manualPins',{})[component]=True;save(state)
            return public_state(state,engine)
        if entry and entry.get('phase')!='prepared':raise ValueError('This map has an interrupted preparation to review.')
        budget=next(row['memoryBytes'] for row in plan['maps'] if row['map']==game['map'])
        resource_policy.admit(state,engine,[partition])
        counters={line.split(':',1)[0]:int(line.split(':',1)[1].strip().split()[0])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if ':' in line and line.split(':',1)[1].strip().split()[0].isdigit()}
        # Existing map limits are ceilings, not committed reservations.
        # MemAvailable already accounts for their current resident usage.
        if counters['MemAvailable']<budget+2*1024**3:
            raise ValueError(f"This start needs {budget/1024**3:.1f} GiB plus 2 GiB host headroom; {counters['MemAvailable']/1024**3:.1f} GiB is available. Stop an unused map or review the host allocation.")
        if not entry:
            template=read_template();credentials=read_credentials(state)
            bridge=engine.request('GET','/networks/'+plan['network'])['IPAM']['Config'][0]['Gateway']
            defaults={name:(Path('/assets/server/scripts/setup/config')/name).read_text() for name in ['UserEngine.ini','UserGame.ini','UserServerCustomSettings.ini']}
            spec=regis_compatibility.apply_image_policy(state,partition,game_spec(plan,partition,credentials,bridge,defaults));files=spec.pop('files')
            entry={'phase':'creating','createdAt':time.time()};state['services'][component]=entry;save(state)
            identifier=engine.create_component(state['id'],component,plan['images']['game']['image'],plan['network'],**spec)
            entry.update(id=identifier,phase='configuring');save(state)
            engine.upload_component_files(identifier,state['id'],component,files)
            entry['phase']='prepared';save(state)
        if state.get('resourcePolicy'):
            engine.set_component_cpu(entry['id'],state['id'],component,state.get('mapCpuOverrides',{}).get(game['map']))
        engine.lifecycle(entry['id'],state['id'],'start')
        state.setdefault('mapTargets',{})[component]='running';save(state)
        manual_floor()
        prepare_map_observers(state,engine)
        if state.get('fileBrowser'):prepare_file_browser(state,engine)
    elif entry:
        observed=engine.assert_owned(entry['id'],state['id'],component)
        if observed['State']['Status']=='running' and not force:
            heartbeat=next((row for row in public_state(state,engine)['services'] if row['component']==component),{})
            if heartbeat.get('players')!=0:raise ValueError('The map has players or its occupancy is unknown. Confirm the stop before retrying.')
        manual_floor()
        if state.get('mapObservers',{}).get(component):engine.lifecycle(state['mapObservers'][component]['id'],state['id'],'stop')
        engine.lifecycle(entry['id'],state['id'],'stop')
    else:manual_floor()
    state.setdefault('mapTargets',{})[component]='running' if running else 'stopped';save(state)
    if not automatic:state.setdefault('manualPins',{})[component]=running;save(state)
    return public_state(state,engine)


def restart_map(state,engine,partition,force=False):
    if type(partition) is not int or not any(row['partition']==partition for row in state.get('worldPlan',{}).get('games',[])) or type(force) is not bool:
        raise ValueError('Choose a map partition from this world to restart.')
    if state.get('desiredState')!='running':raise ValueError('Start the battlegroup before restarting a map.')
    component='game-'+str(partition);entry=state.get('services',{}).get(component)
    if not entry or engine.assert_owned(entry['id'],state['id'],component)['State']['Status']!='running':
        return {'noop':True,'restarted':0}
    if not force:
        observed=next((row for row in public_state(state,engine)['services'] if row['component']==component),{})
        if observed.get('players')!=0:raise ValueError('The map has players or its occupancy is unknown. Confirm the restart before retrying.')
    reader=state.get('mapObservers',{}).get(component)
    if reader:engine.lifecycle(reader['id'],state['id'],'stop')
    engine.lifecycle(entry['id'],state['id'],'stop')
    # A restart preserves the saved warm floor and manual pin. Reuse admission,
    # native process startup and observer reconnection without a policy edit.
    targets=state.get('mapTargets',{})
    explicit=component in targets;previous=targets.get(component)
    try:control_map(state,engine,partition,True,force=True,automatic=True)
    finally:
        if explicit:state.setdefault('mapTargets',{})[component]=previous
        else:state.get('mapTargets',{}).pop(component,None)
        save(state)
    return {'noop':False,'restarted':1}


def set_resources(state,engine,request):
    change=resource_policy.validate_change(state,request,resource_policy.host_capacity())
    pending=state.get('pendingResourceChange')
    if pending and {key:value for key,value in pending.items() if key!='cpuCount'}!=change:
        raise ValueError('Retry the pending resource allocation before choosing different values.')
    entries=[]
    for component,entry in state.get('services',{}).items():
        if not component.startswith('game-'):continue
        observed=engine.assert_owned(entry['id'],state['id'],component)
        row=next(row for row in state['worldPlan']['maps'] if int(component[5:]) in row['partitions'])
        allocation=next(item for item in change['maps'] if item['map']==row['map'])
        entries.append((component,entry['id'],allocation,observed.get('HostConfig',{}).get('Memory',0)))
    entries.sort(key=lambda entry: int(entry[2]['memoryGiB']*1024**3)-entry[3])
    state['pendingResourceChange']=change;save(state)
    for component,identifier,allocation,previous in entries:
        if state.get('memorySwap'):engine.set_component_memory(identifier,state['id'],component,int(allocation['memoryGiB']*1024**3),state['memorySwap'])
        else:engine.set_component_memory(identifier,state['id'],component,int(allocation['memoryGiB']*1024**3))
        engine.set_component_cpu(identifier,state['id'],component,allocation['cpus'])
    state['resourcePolicy']={'memoryGiB':change['memoryGiB']}
    state['mapMemoryOverrides']={item['map']:int(item['memoryGiB']*1024**3) for item in change['maps']}
    state['mapCpuOverrides']={item['map']:item['cpus'] for item in change['maps']}
    for row in state.get('worldPlan',{}).get('maps',[]):row['memoryBytes']=state['mapMemoryOverrides'][row['map']]
    if state.get('worldPlan'):
        state['worldPlan']['initialMemoryBytes']=sum(row['memoryBytes']*row['initialReplicas'] for row in state['worldPlan']['maps'])
    state.pop('pendingResourceChange');save(state)
    return resource_policy.snapshot(state,engine)


def set_map_memory(state,engine,map_name,gib):
    if type(gib) not in {int,float} or not 0.25<=gib<=128:raise ValueError('Choose a memory limit between 0.25 and 128 GiB.')
    rows=[row for row in state.get('worldPlan',{}).get('maps',[]) if row['map']==map_name]
    if len(rows)!=1:raise ValueError('Choose a map in the installed world.')
    amount=int(gib*1024**3);pending=state.get('pendingMemoryChange')
    if pending and (pending['map']!=map_name or pending['bytes']!=amount):raise ValueError('Finish the pending map memory allocation first.')
    counters={line.split(':',1)[0]:line.split(':',1)[1].strip().split()[0] for line in Path('/proc/meminfo').read_text().splitlines()}
    instances=[];reserved=0;increase=0
    for component,entry in state.get('services',{}).items():
        if not component.startswith('game-'):continue
        current=engine.assert_owned(entry['id'],state['id'],component)
        selected=int(component[5:]) in rows[0]['partitions']
        previous=current['HostConfig']['Memory']
        if selected:
            instances.append((component,entry['id']))
        if current['State']['Status']=='running':
            reserved+=amount if selected else previous
            if selected:increase+=max(0,amount-previous)
    raising=amount>rows[0]['memoryBytes']
    if raising and (reserved>int(counters['MemTotal'])*1024-2*1024**3 or increase+2*1024**3>int(counters['MemAvailable'])*1024):
        raise ValueError('The requested map allocation needs more memory than is available with 2 GiB host headroom.')
    budget=state.get('resourcePolicy',{}).get('memoryGiB')
    if raising and budget is not None and max(reserved,amount)+resource_policy.SERVICE_RESERVE>budget*1024**3:
        raise ValueError('This map limit exceeds the server RAM budget with its supporting services. Lower it or change the host allocation in Settings.')
    state['pendingMemoryChange']={'map':map_name,'bytes':amount};save(state)
    for component,identifier in instances:
        if state.get('memorySwap'):engine.set_component_memory(identifier,state['id'],component,amount,state['memorySwap'])
        else:engine.set_component_memory(identifier,state['id'],component,amount)
    state.setdefault('mapMemoryOverrides',{})[map_name]=amount
    rows[0]['memoryBytes']=amount
    state['worldPlan']['initialMemoryBytes']=sum(row['memoryBytes']*row['initialReplicas'] for row in state['worldPlan']['maps'])
    state.pop('pendingMemoryChange');save(state)
    return {'map':map_name,'memoryGiB':gib,'containersUpdated':len(instances),'restartRequired':False}


def request_scale(state,engine,name,patch):
    if not state.get('scaler',{}).get('coreAdapterApplied') or state.get('desiredState')!='running':
        raise ValueError('Native map orchestration is not active.')
    map_info,partitions=parse_patch(state,name,patch)
    old=desired_partitions(state,map_info)
    if state.get('mapModes',{}).get(map_info['map'])=='disabled' and set(partitions)-set(old):
        raise ValueError('This map is disabled. Choose another map mode before starting it.')
    if not state.get('memoryBalancingEnabled', True) and map_info['map'] not in state.get('classicAutomaticMaps',[]):
        # Classic operation keeps explicitly started maps available. Manual
        # map stops and Stop All still update their targets normally.
        retained=[partition for partition in old if state.get('manualPins',{}).get('game-'+str(partition)) is not False]
        partitions=sorted(set(partitions)|set(retained))
    if old==partitions:return scale_resource(state,map_info)
    pins=state.get('manualPins',{})
    for index,partition in enumerate(map_info['partitions']):
        if partition not in partitions and pins.get('game-'+str(partition),index<map_info['initialReplicas']):
            raise ValueError('The selected map has an explicit warm floor.')
    observed=public_state(state,engine)
    for partition in set(old)-set(partitions):
        component='game-'+str(partition)
        service=next((row for row in observed['services'] if row['component']==component),{})
        if service.get('state')=='running' and service.get('players')!=0:
            raise ValueError('The map is occupied or its occupancy is unknown.')
    previous={component:state.get('mapTargets',{}).get(component) for component in ['game-'+str(value) for value in map_info['partitions']]}
    for partition in map_info['partitions']:state.setdefault('mapTargets',{})['game-'+str(partition)]='running' if partition in partitions else 'stopped'
    state['scaleRevision']=state.get('scaleRevision',0)+1
    request={'action':'scale.apply','partitions':partitions,'availablePartitions':map_info['partitions'],'previousTargets':previous}
    state['operation']={'id':uuid.uuid4().hex,'action':'scale.apply','phase':'running','startedAt':time.time()}
    state['scalePending']={**request,'operationId':state['operation']['id'],'phase':'running'};save(state)
    response=scale_resource(state,map_info)
    threading.Thread(target=run_operation,args=(state,engine,request),daemon=True).start()
    return response


def apply_scale(state,engine,request):
    try:
        for partition in request['availablePartitions']:
            # Director stop requests can have been decided before a player
            # returned to Overmap. Recheck before signalling the game process.
            stopping=partition not in request['partitions']
            game=next((row for row in state['worldPlan'].get('games',[]) if row['partition']==partition),{}) if stopping else {}
            following=state.get('mapModes',{}).get(game.get('map'))=='overmap-active'
            if stopping and following and follow_overmap_demand(state,engine) is not False:
                set_map_floor(state,engine,game['map'],True)
                control_map(state,engine,partition,True,automatic=True)
                continue
            control_map(state,engine,partition,partition in request['partitions'],automatic=True)
            # A signalled process must finish draining. Renewed demand must
            # then restart it, rather than leave a warm-but-stopped target.
            if stopping and following and follow_overmap_demand(state,engine) is True:
                set_map_floor(state,engine,game['map'],True)
                control_map(state,engine,partition,True,automatic=True)
        state['scalePending']['phase']='completed';save(state)
    except Exception:
        for component,previous in request['previousTargets'].items():
            entry=state.get('services',{}).get(component)
            try:running=entry and engine.assert_owned(entry['id'],state['id'],component)['State']['Status']=='running'
            except Exception:running=previous=='running'
            state.setdefault('mapTargets',{})[component]='running' if running else 'stopped'
        state['scalePending']['phase']='failed';save(state)
        raise


def recover_interrupted_scale(state,engine):
    pending=state.get('scalePending',{})
    if pending.get('phase')!='running':return
    # A manager restart can interrupt the response after Docker has acted.
    # Reconcile owned containers instead of replaying an ambiguous mutation.
    for partition in pending.get('availablePartitions',[]):
        component='game-'+str(partition)
        entry=state.get('services',{}).get(component)
        running=bool(entry and engine.assert_owned(entry['id'],state['id'],component)['State']['Status']=='running')
        state.setdefault('mapTargets',{})[component]='running' if running else 'stopped'
    pending['phase']='interrupted'
    state['scaleRevision']=state.get('scaleRevision',0)+1
    save(state)


def map_policy(state,engine):
    entry=state.get('services',{}).get('director')
    if not entry:raise ValueError('Prepare the world services first.')
    return {'ini':engine.read_director_config(entry['id'],state['id']).decode(),
            'world':state['worldId'],'maps':state['worldPlan']['maps']}


def set_map_floor(state,engine,map_name,enabled,allow_initial=False):
    if type(enabled) is not bool:raise ValueError('enabled must be a JSON boolean.')
    maps=[row for row in state['worldPlan']['maps'] if row['map']==map_name and (allow_initial or row['initialReplicas']==0)]
    if len(maps)!=1:raise ValueError('This map does not have a configurable warm floor.')
    policy=map_policy(state,engine)
    pins=dict(state.get('manualPins',{}))
    for partition in maps[0]['partitions']:pins['game-'+str(partition)]=enabled
    config=native_director_ini(policy['ini'],state['worldPlan'],pins,state.get('mapModes'))
    engine.upload_component_files(state['services']['director']['id'],state['id'],'director',{
        'Tools/Battlegroups/Director/BattlegroupDirector/director_config.ini':{'data':config}})
    state['manualPins']=pins;state['directorIni']=config;save(state)
    scaler=state.get('scaler',{})
    director=state['services']['director']['id']
    if scaler.get('phase')=='prepared' and engine.assert_owned(director,state['id'],'director')['State']['Status']=='running':
        engine.set_director_floor(scaler['id'],director,state['id'],map_name,len(maps[0]['partitions']) if enabled else 0)
    return {'map':map_name,'enabled':enabled,'minServers':len(maps[0]['partitions']) if enabled else 0,
            'availablePartitions':len(maps[0]['partitions'])}


def set_party_sharing(state,engine,map_name,shared):
    if map_name!='CB_Story_DestroyedZanovar' or type(shared) is not bool:
        raise ValueError('Choose the supported party-sharing map and a JSON boolean.')
    policy=map_policy(state,engine)
    config=party_sharing_ini(policy['ini'],map_name,shared)
    if config!=policy['ini']:
        engine.upload_component_files(state['services']['director']['id'],state['id'],'director',{
            'Tools/Battlegroups/Director/BattlegroupDirector/director_config.ini':{'data':config}})
        state['directorIni']=config;save(state)
    # The installed director reloads these INI settings every 60 seconds, just
    # as in the VM deployment. No map/director restart or live override needed.
    return {'map':map_name,'sharedParties':shared,'noop':config==policy['ini'],'applyDelaySeconds':60}


def set_map_mode(state,engine,map_name,mode):
    row=next((row for row in state.get('worldPlan',{}).get('maps',[]) if row['map']==map_name),None)
    if not row or row.get('initialReplicas',0)>0 or not isinstance(mode,str) or mode not in map_modes.MODES:
        raise ValueError('Choose a supported lifecycle mode for an optional map. Core maps stay available.')
    previous=dict(state.get('mapModes',{}))
    pending=state.get('pendingMapMode')
    if pending and (pending['map']!=map_name or pending['mode']!=mode):
        raise ValueError('Retry the pending map mode before changing another map rule.')
    state['pendingMapMode']={'map':map_name,'mode':mode};save(state)
    state.setdefault('mapModes',{})[map_name]=mode
    warm=mode=='always-on' or (mode=='overmap-active' and any(state.get('manualPins',{}).get('game-'+str(p),False) for p in row['partitions']))
    try:set_map_floor(state,engine,map_name,warm)
    except Exception:
        state['mapModes']=previous
        state['mapModeError']='The map mode change did not finish. Retry the recorded selection; map starts remain blocked until it is reconciled.'
        save(state)
        raise
    state.setdefault('overmapIdleSince',{}).pop(map_name,None)
    state.pop('pendingMapMode',None);state.pop('mapModeError',None)
    save(state)
    return {'map':map_name,'mode':mode,'message':'Map mode saved. The director reloads its rules within 60 seconds. Running maps are not forcibly stopped.'}


def scheduler_occupancy(state,engine):
    """Use current process identities and online rows, never heartbeat player lists."""
    counts={row['partition']:None for row in state['worldPlan']['games']}
    director=state.get('services',{}).get('director')
    if not director:return counts
    heartbeats=engine.game_heartbeats(director['id'],state['id'])
    identities={}
    for game in state['worldPlan']['games']:
        partition=game['partition'];component='game-'+str(partition)
        entry=state.get('services',{}).get(component)
        if not entry:
            counts[partition]=0;continue
        observed=engine.assert_owned(entry['id'],state['id'],component)
        if observed['State']['Status'] not in {'running','restarting'}:
            counts[partition]=0;continue
        heartbeat=heartbeats.get(partition,{})
        started=datetime.fromisoformat(observed['State']['StartedAt'].replace('Z','+00:00')).timestamp()
        identity=heartbeat.get('serverId','')
        if heartbeat.get('observedAt',0)>=started and re.fullmatch(r'[A-Za-z0-9_+/-]{22}',identity):
            identities[partition]=identity
    if not identities:return counts
    quoted=','.join("'"+value+"'" for value in sorted(set(identities.values())))
    query="SELECT coalesce(json_object_agg(server_id,players),'{}'::json) FROM (SELECT server_id::text,count(*) AS players FROM dune.encrypted_player_state WHERE online_status::text <> 'Offline' AND server_id IN ("+quoted+") GROUP BY server_id) AS online;"
    raw=engine.exec_internal(state['database']['id'],state['id'],'postgres',
        ['psql','-X','-U','dune','-d','dune','-v','ON_ERROR_STOP=1','-t','-A','-c',
         "BEGIN READ ONLY; SET LOCAL statement_timeout='3s'; "+query+' COMMIT;'])
    # psql can include transaction command tags around the one JSON row.
    values=json.loads(next(line for line in raw.splitlines() if line.strip().startswith('{')))
    for partition,identity in identities.items():
        value=values.get(identity,0)
        if type(value) is not int or value<0:raise ValueError('Invalid online map occupancy.')
        counts[partition]=value
    return counts


def follow_overmap_demand(state,engine):
    counts=scheduler_occupancy(state,engine)
    partitions=[row['partition'] for row in state['worldPlan']['games'] if row['map']=='Overmap']
    if not partitions or any(counts.get(p) is None for p in partitions):return None
    return sum(counts[p] for p in partitions)>0


def queue_follow_overmap_starts(state,engine,rows):
    partitions=[]
    for row in rows:
        for partition in row['partitions']:
            component='game-'+str(partition);entry=state.get('services',{}).get(component)
            running=bool(entry and engine.assert_owned(entry['id'],state['id'],component)['State']['Status']=='running')
            if not running or state.get('mapTargets',{}).get(component)!='running':partitions.append(partition)
    if not partitions:return
    previous={'game-'+str(p):state.get('mapTargets',{}).get('game-'+str(p)) for p in partitions}
    for p in partitions:state.setdefault('mapTargets',{})['game-'+str(p)]='running'
    state['scaleRevision']=state.get('scaleRevision',0)+1
    request={'action':'scale.apply','partitions':partitions,'availablePartitions':partitions,'previousTargets':previous}
    state['operation']={'id':uuid.uuid4().hex,'action':'scale.apply','phase':'running','startedAt':time.time()}
    state['scalePending']={**request,'operationId':state['operation']['id'],'phase':'running'};save(state)
    threading.Thread(target=run_operation,args=(state,engine,request),daemon=True).start()


def map_mode_tick(engine=None,now=None):
    engine=engine or Engine();now=time.time() if now is None else now
    # Occupancy I/O must not monopolize the management lock or socket listener.
    with LOCK:snapshot=project_state()
    if snapshot.get('desiredState')!='running':return
    if not any(map_modes.mode_for(snapshot,row)=='overmap-active' for row in snapshot.get('worldPlan',{}).get('maps',[])):return
    counts=scheduler_occupancy(snapshot,engine)
    with LOCK:
        state=project_state()
        if state.get('id')!=snapshot.get('id') or state.get('services')!=snapshot.get('services'):return
        if state.get('desiredState')!='running' or state.get('operation',{}).get('phase')=='running':return
        if any(state.get(key) for key in ('pendingMemoryChange','pendingResourceChange','pendingSwapChange','pendingRegisChange','pendingAddressChange','pendingMapMode')):return
        if state.get('restore',{}).get('phase') in {'stopping','preparing','restoring','recovering','recovery-required'}:return
        if state.get('updateRun',{}).get('phase','completed') not in world_update.TERMINAL:return
        if state.get('worldRestart',{}).get('phase','done') not in world_restart.TERMINAL:return
        if state.get('worldResearchRecovery',{}).get('phase','completed') not in {'completed','rolled-back','failed-preflight'}:return
        rows=[row for row in state.get('worldPlan',{}).get('maps',[]) if map_modes.mode_for(state,row)=='overmap-active']
        if not rows:return
        games=state['worldPlan']['games']
        def occupancy(map_name):
            partitions={row['partition'] for row in games if row['map']==map_name}
            if not partitions or any(counts.get(p) is None for p in partitions):return None
            return sum(counts[p] for p in partitions)
        players=occupancy('Overmap')
        # One shared inactivity clock; joining Overmap resets it for every map.
        _,since=map_modes.overmap_floor(players,0,state.get('overmapEmptySince'),now)
        state['overmapEmptySince']=since
        for row in rows:
            floor,_=map_modes.overmap_floor(players,occupancy(row['map']),since,now)
            if floor is not None and any(state.get('manualPins',{}).get('game-'+str(p),False)!=floor for p in row['partitions']):
                set_map_floor(state,engine,row['map'],floor)
        state.pop('mapModeError',None);save(state)
        if players is not None and players>0:queue_follow_overmap_starts(state,engine,rows)


def run_map_mode_scheduler():
    while True:
        try:map_mode_tick()
        except Exception:
            with LOCK:
                state=project_state();state['mapModeError']='Overmap Active could not refresh its map rules. Check map status and retry the mode setting.';save(state)
        time.sleep(15)


def stop_services(state,engine):
    state['desiredState']='stopped';save(state)
    for observer in state.get('mapObservers',{}).values():engine.lifecycle(observer['id'],state['id'],'stop')
    services=state.get('services',{})
    order=[name for name in services if name.startswith('game-')]+['gateway','director','text-router']
    for component in order:
        if services.get(component,{}).get('id'):
            engine.lifecycle(services[component]['id'],state['id'],'stop')
    for component,entry in state.get('connections',{}).items():
        if entry.get('id'):engine.lifecycle(entry['id'],state['id'],'stop')
    if state.get('scaler',{}).get('id'):engine.lifecycle(state['scaler']['id'],state['id'],'stop')
    return public_state(state,engine)


def refresh_game_adapters(state,engine):
    if state.get('desiredState')!='stopped':raise ValueError('Stop the world before updating game adapters.')
    games={name:entry for name,entry in state.get('services',{}).items() if name.startswith('game-')}
    if not games:raise ValueError('Prepare the game services first.')
    for component,entry in games.items():
        observed=engine.assert_owned(entry['id'],state['id'],component)
        if entry['phase']!='prepared' or observed['State']['Status'] not in {'exited','created'}:
            raise ValueError('Every game process must finish stopping before its adapter is updated.')
        expected='dst-'+state['id']+'-'+component+'-saved'
        saved=[mount for mount in observed.get('Mounts',[]) if mount.get('Destination')=='/home/dune/server/DuneSandbox/Saved']
        if len(saved)!=1 or saved[0].get('Type')!='volume' or saved[0].get('Name')!=expected:
            raise ValueError('Existing game storage needs review; it was left unchanged.')
    plan=state['worldPlan'];credentials=read_credentials(state)
    network=engine.request('GET','/networks/'+plan['network'])
    bridge=network['IPAM']['Config'][0]['Gateway']
    for component,previous in games.items():
        partition=int(component.removeprefix('game-'))
        spec=regis_compatibility.apply_image_policy(state,partition,game_spec(plan,partition,credentials,bridge,{}))
        for volume in spec['volumes']:volume['mustBeNew']=False
        entry={'phase':'retiring','previous':previous};state['services'][component]=entry;save(state)
        entry['previousName']=engine.retire_game_container(previous['id'],state['id'],component);save(state)
        source=plan['images']['game'];files=spec.pop('files')
        identifier=engine.create_component(state['id'],component,source['image'],plan['network'],**spec)
        entry.update(id=identifier,phase='configuring');save(state)
        engine.upload_component_files(identifier,state['id'],component,files)
        entry['phase']='prepared';save(state)
    return public_state(state,engine)


def network_profile(state,request):
    if state.get('pendingAddressChange') or state.get('generationChange'):
        raise ValueError('Recover the interrupted network update before applying another change.')
    if not state.get('profile') or not state.get('services'):
        raise ValueError('Finish preparing your world before changing player access.')
    if request.get('expectedAddress')!=state['profile']['address']:
        raise ValueError('The server address changed. Refresh Settings before applying.')
    mode=request.get('mode')
    if mode not in {'private','public'}:raise ValueError('Choose Private / LAN or Public / External.')
    if not isinstance(request.get('address'),str):raise ValueError('Enter a valid IPv4 address.')
    try:address=ipaddress.IPv4Address(request.get('address'))
    except (ValueError,TypeError):raise ValueError('Enter a valid IPv4 address.') from None
    local=address.is_loopback or any(address in ipaddress.IPv4Network(cidr) for cidr in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))
    if mode=='public' and (not address.is_global or address.is_multicast):
        raise ValueError('Public / External requires a public IPv4 address.')
    if mode=='private' and not local:
        raise ValueError('Private / LAN requires a LAN or loopback IPv4 address.')
    return validate_profile({**state['profile'],'address':str(address),'gamePortBase':7777})


def set_network(state,engine,request):
    profile=network_profile(state,request)
    if profile==state['profile'] and state['worldPlan']['ports']['rmq-game']==31982:return
    # Reject an incompatible package before stopping a healthy world.
    template=read_template()
    if template['sha256']!=state['worldPlan']['templateSha256']:
        raise ValueError('The installed game package changed; review the server update before changing network settings.')
    plan_world(state['id'],profile,template,assets_state(),state['database'],state.get('mapMemoryOverrides'),state.get('memorySwap'))
    resume=state.get('desiredState')=='running'
    if state.get('operation',{}).get('action')=='network.set':
        state['operation'].update(stage='stopping',targetAddress=profile['address'],targetMode=request['mode'],resume=resume);save(state)
    stop_services(state,engine)
    if state.get('operation',{}).get('action')=='network.set':state['operation']['stage']='reconfiguring';save(state)
    reconfigure_address(state,engine,profile)
    if resume:
        if state.get('operation',{}).get('action')=='network.set':state['operation']['stage']='restarting';save(state)
        start_services(state,engine)


def reconfigure_address(state,engine,profile):
    if state.get('desiredState')!='stopped':raise ValueError('Stop the world before changing its connection address.')
    if state.get('pendingAddressChange'):raise ValueError('The previous address update needs recovery before another can start.')
    for collection in ['connections','services']:
        for component,entry in state.get(collection,{}).items():
            observed=engine.assert_owned(entry['id'],state['id'],component)
            if entry['phase']!='prepared' or observed['State']['Status'] not in {'exited','created'}:
                raise ValueError('Wait for every component to finish stopping before changing its address.')
    template=read_template()
    if template['sha256']!=state['worldPlan']['templateSha256']:
        raise ValueError('The installed game package changed; review the server update before changing network settings.')
    # Preserve the actual installed INI, including deliberate manual changes.
    director_ini=engine.read_director_config(state['services']['director']['id'],state['id'])
    plan=plan_world(state['id'],profile,template,assets_state(),state['database'],state.get('mapMemoryOverrides'),state.get('memorySwap'))
    state['pendingAddressChange']={'previousProfile':state['profile'],'previousPlan':state['worldPlan'],'startedAt':time.time()}
    state.update(profile=profile,worldPlan=plan);save(state)
    credentials=read_credentials(state)
    specifications={name:queue_spec(name,plan,template,credentials['tls']) for name in ['rmq-admin','rmq-game']}
    specifications.update(service_specs(plan,template,credentials))
    specifications['director']['files']['Tools/Battlegroups/Director/BattlegroupDirector/director_config.ini']['data']=director_ini
    network=engine.request('GET','/networks/'+plan['network'])
    bridge=network['IPAM']['Config'][0]['Gateway']
    for component in state['services']:
        if component.startswith('game-'):
            spec=regis_compatibility.apply_image_policy(state,int(component.removeprefix('game-')),game_spec(plan,int(component.removeprefix('game-')),credentials,bridge,{}),plan=plan)
            for volume in spec['volumes']:volume['mustBeNew']=False
            specifications[component]=spec
    service_generations.replace_generation(state,engine,specifications,plan,save,'address',
        previous_plan=state['pendingAddressChange']['previousPlan'],previous_profile=state['pendingAddressChange']['previousProfile'])
    state['connections']['rmq-game']['tlsSha256']=hashlib.sha256(credentials['tls']['ca.pem']+credentials['tls']['cert.pem']).hexdigest()
    service_generations.commit_generation(state,save)
    change=state.pop('pendingAddressChange');change['finishedAt']=time.time()
    state.setdefault('addressChangeHistory',[]).append(change);save(state)
    return public_state(state,engine)


def configure_world(state,engine,profile):
    profile=validate_profile(profile)
    if state['phase']!='database-ready': raise ValueError('Install the game database schema first.')
    if state.get('connections') and profile!=state.get('profile'):
        previous=state['profile']
        if {key:value for key,value in profile.items() if key not in {'address','name'}}!={key:value for key,value in previous.items() if key not in {'address','name'}}:
            raise ValueError('These installed world settings need review before they can be changed.')
        return reconfigure_address(state,engine,profile)
    if state.get('partitionsPrepared'):
        state['profile']=profile; save(state)
        return public_state(state,engine)
    template=read_template()
    rows=template['partitions']
    database=state['database']
    engine.assert_owned(database['id'],state['id'],'postgres')
    command=['psql','-X','-U','dune','-d','dune','-v','ON_ERROR_STOP=1','-t','-A','-c']
    count=int(engine.exec_internal(database['id'],state['id'],'postgres',command+['SELECT count(*) FROM dune.world_partition']).strip())
    if count==0:
        state['partitionPlan']={'sha256':template['sha256'],'rows':rows}
        save(state)
        engine.exec_internal(database['id'],state['id'],'postgres',command+[fresh_partition_sql(rows)])
    else:
        if state.get('partitionPlan',{}).get('rows')!=rows:
            raise ValueError('Existing world partitions need review; they were left unchanged.')
    verify_sql="SELECT coalesce(jsonb_agg(jsonb_build_object('id',partition_id,'map',map,'dimension',dimension_index,'blocked',blocked,'definition',partition_definition) ORDER BY partition_id),'[]'::jsonb) FROM dune.world_partition"
    actual=json.loads(engine.exec_internal(database['id'],state['id'],'postgres',command+[verify_sql]))
    if actual!=rows: raise ValueError('World partition readback did not match the official template.')
    state.update(profile=profile,partitionsPrepared=True)
    save(state)
    return public_state(state,engine)


def rename_world(state,engine,name):
    if not state.get('profile'):raise ValueError('Prepare the world before renaming it.')
    if not isinstance(name,str):raise ValueError('Enter a world name.')
    profile=validate_profile({**state['profile'],'name':name.strip()})
    if profile==state['profile']:return
    resume=state.get('desiredState')=='running'
    if resume:stop_services(state,engine)
    configure_world(state,engine,profile)
    if resume:start_services(state,engine)


def migrate_database(state,engine):
    if state['phase']=='database-ready': return public_state(state,engine)
    if state['phase'] not in {'database-initialized','database-migration-failed'}: raise ValueError('Prepare the database before installing its game schema.')
    images=assets_state()['images']
    tags=[tag for entry in images if entry['archive']=='battlegroup/server-db-utils.tar' for tag in entry['tags']]
    if len(tags)!=1: raise ValueError('Official database utilities image is unavailable.')
    engine.ensure_package_image('/assets/server/images/battlegroup/server-db-utils.tar',tags[0])
    self_container=engine.inspect(os.environ['HOSTNAME'])
    mounts=[mount for mount in self_container.get('Mounts',[]) if mount.get('Destination')=='/projects' and mount.get('Type')=='volume']
    if len(mounts)!=1: raise ValueError('Private project storage could not be identified.')
    backup_name='pre-migration-'+str(int(time.time()))+'-'+secrets.token_hex(4)+'.dump'
    if state.get('migration'):
        state.setdefault('migrationHistory',[]).append(state['migration'])
    state['phase']='database-migration-preparing'; save(state)
    database=state['database']
    identifier=engine.create_migration_job(state['id'],tags[0],database['network'],mounts[0]['Name'],database['name'],
        Path('/opt/dst-manager/migration-job.py').read_text(),'dst-'+state['id']+'-backups',backup_name)
    state.update(phase='database-migrating',migration={'id':identifier,'backup':backup_name})
    save(state)
    engine.lifecycle(identifier,state['id'],'start')
    return public_state(state,engine)


def provision_database(state, engine, port):
    if state.get('database'): return public_state(state, engine)
    if state['phase'] != 'new': raise ValueError('A previous provisioning attempt needs recovery before another can start.')
    assets = assets_state()
    if assets['state'] != 'downloaded': raise ValueError('Download the official server package first.')
    tags = [tag for entry in assets['images'] if entry['archive']=='prerequisites/igw-postgres.tar' for tag in entry['tags']]
    if len(tags) != 1: raise ValueError('The official database image could not be identified.')
    engine.ensure_package_image('/assets/server/images/prerequisites/igw-postgres.tar', tags[0])
    password = secrets.token_urlsafe(40)
    atomic(STATE / 'postgres-admin.password', password)
    state['phase'] = 'creating-database'
    save(state)  # An ambiguous Docker response never authorizes a second create.
    try:
        database = engine.create_database(state['id'], tags[0], port, password)
    except Exception:
        state['phase'] = 'database-create-needs-recovery'
        save(state)
        raise
    state.update(database=database, phase='database-starting')
    save(state)
    return public_state(state, engine)


def initialize_database(state, engine):
    database = state.get('database')
    if not database: raise ValueError('Create the database first.')
    if state['phase'] in {'database-initialized','database-migrating','database-ready','database-migration-failed'}: return public_state(state, engine)
    observed = engine.assert_owned(database['id'], state['id'], 'postgres')
    if observed.get('State', {}).get('Health', {}).get('Status') != 'healthy':
        raise ValueError('The database is still starting.')
    password_file = STATE / 'dune-app.password'
    if not password_file.exists(): atomic(password_file, secrets.token_urlsafe(40))
    password = password_file.read_text()
    # Token_urlsafe generates no SQL quote characters. This internal bootstrap
    # is never populated from arbitrary browser SQL or a user-supplied path.
    command = ['psql','-X','-U','postgres','-d','postgres','-v','ON_ERROR_STOP=1','-c']
    role_sql = "DO $$BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='dune') THEN CREATE ROLE dune LOGIN; END IF; END$$; ALTER ROLE dune WITH LOGIN PASSWORD '" + password + "';"
    engine.exec_internal(database['id'], state['id'], 'postgres', command + [role_sql])
    exists = engine.exec_internal(database['id'], state['id'], 'postgres', command[:-1] + ['-t','-A','-c',"SELECT 1 FROM pg_database WHERE datname='dune'"]).strip()
    if exists != '1':
        engine.exec_internal(database['id'], state['id'], 'postgres', ['createdb','-U','postgres','-O','dune','dune'])
    CONFIG.mkdir(parents=True, exist_ok=True)
    atomic(CONFIG / 'docker-db.password', password, 0o640, 10001)
    settings = {'host':'127.0.0.1','port':database['port'],'database':'dune','user':'dune',
                'passwordFile':'/data/config/DuneServer/docker-db.password','allowWrites':True}
    atomic(CONFIG / 'docker-database.json', json.dumps(settings), 0o640, 10001)
    state['phase'] = 'database-initialized'
    save(state)
    return public_state(state, engine)


def run_operation(state,engine,request):
    action=request['action']
    try:
        if action=='database.create':provision_database(state,engine,request.get('port',18932))
        elif action=='database.initialize':initialize_database(state,engine)
        elif action=='database.migrate':migrate_database(state,engine)
        elif action=='database.start':ensure_database_ready(state,engine)
        elif action=='database.stop':stop_database_only(state,engine)
        elif action=='world.configure':configure_world(state,engine,request.get('profile',{}))
        elif action=='network.set':set_network(state,engine,request)
        elif action=='world.rename':rename_world(state,engine,request.get('name'))
        elif action=='connections.prepare':prepare_connections(state,engine)
        elif action=='services.prepare':prepare_services(state,engine)
        elif action=='services.start':start_services(state,engine,publish_gateway=request.get('publishGateway',True))
        elif action=='services.stop':stop_services(state,engine)
        elif action=='services.restart':
            # Reject genuine plan conflicts before taking a healthy world down.
            validate_connection_plan(state)
            stop_services(state,engine)
            start_services(state,engine)
        elif action in {'maps.start','maps.stop'}:control_map(state,engine,request.get('partition'),action=='maps.start',request.get('force',False))
        elif action=='maps.restart':state['operation']['result']=restart_map(state,engine,request.get('partition'),request.get('force',False))
        elif action=='maps.observers.prepare':prepare_map_observers(state,engine)
        elif action=='files.prepare':prepare_file_browser(state,engine)
        elif action=='settings.prepare':prepare_settings_service(state,engine)
        elif action=='regis.set':state['operation']['result']=regis_compatibility.Compatibility(state,engine,sys.modules[__name__]).set(request['enabled'],request.get('acknowledgeStoredTanks',False))
        elif action=='regis.recover':state['operation']['result']=regis_compatibility.Compatibility(state,engine,sys.modules[__name__]).recover()
        elif action=='memory-swap.set':state['operation']['result']=memory_swap_control.configure(state,engine,save,request)
        elif action=='memory-swap.recover':state['operation']['result']=memory_swap_control.recover(state,engine,save,request.get('restorePrevious',False))
        elif action=='logs.export':state['operation']['result']=export_logs(state,engine,request.get('scope'),state['operation']['id'])
        elif action=='updates.stage':state['operation']['result']=asset_updates.start_stage(state,engine,request.get('expectedBuild'),save)
        elif action=='updates.apply':state['operation']['result']=world_update.NativeUpdate(state,engine,sys.modules[__name__]).apply(request.get('expectedBuild'),request.get('allowOnline',False),request.get('withTanks',False))
        elif action=='updates.recover':world_update.NativeUpdate(state,engine,sys.modules[__name__]).recover()
        elif action=='rmq.publish':state['operation']['result']=publish_commands(state,engine,request.get('fields'),request.get('authToken'),request.get('spacingMilliseconds',0))
        elif action=='rmq.courier':state['operation']['result']=publish_courier(state,engine,request.get('courier'))
        elif action=='scale.prepare':prepare_scaler(state,engine)
        elif action=='scale.apply':apply_scale(state,engine,request)
        elif action=='services.refresh-core-adapters':refresh_core_adapters(state,engine)
        elif action=='games.refresh-adapters':refresh_game_adapters(state,engine)
        elif action=='backups.create':start_backup(state,engine)
        elif action=='backups.verify':start_backup(state,engine,request.get('backupId',''))
        elif action=='backups.restore':restore_backup(state,engine,request.get('backupId',''),request.get('confirmation',''))
        elif action=='backups.delete':start_backup_cleanup(state,engine,request.get('backupIds'))
        elif action=='backups.cleanup.recover':recover_backup_cleanup(state,engine)
        elif action=='backups.export':start_backup_export(state,engine,request.get('backupId'))
        elif action=='backups.import':start_backup_import(state,engine,request)
        elif action=='backups.schedule.recover':recover_scheduled_backup(state,engine)
        elif action=='backups.mirror.sync':backup_mirror_control.start(state,engine,save,check_all=True)
        elif action=='backups.mirror.recover':backup_mirror_control.start(state,engine,save,retry=True)
        elif action=='world-restart.apply':world_restart.NativeWorldRestart(state,engine,sys.modules[__name__]).apply(request.get('confirmation'))
        elif action=='world-restart.recover':world_restart.NativeWorldRestart(state,engine,sys.modules[__name__]).recover()
        elif action=='world-restart.rollback':world_restart.NativeWorldRestart(state,engine,sys.modules[__name__]).rollback(request.get('confirmation'))
        elif action=='world-restart.research':world_research.NativeResearchRecovery(state,engine,sys.modules[__name__]).apply_research(request.get('confirmation'),request.get('characterName'),request.get('funcomId'),request.get('itemKeys'))
        elif action=='world-restart.research-recover':world_research.NativeResearchRecovery(state,engine,sys.modules[__name__]).recover()
        else:raise ValueError('Unsupported Docker operation.')
        state['operation'].update(phase='completed',finishedAt=time.time())
    except (ValueError,EngineError) as error:
        state['operation'].update(phase='failed',error=str(error),finishedAt=time.time())
    except Exception:
        state['operation'].update(phase='failed',error='The Docker operation needs review. Existing server data was preserved.',finishedAt=time.time())
    finally:save(state)


def dispatch(request, engine=None, *, resume_running_only=False):
    engine = engine or Engine()
    action = request.get('action')
    if action in {'status','maps.management'}:
        # Read the atomically saved state without waiting behind director I/O.
        # Job transitions are observed only by the request owning the lock.
        acquired=LOCK.acquire(blocking=False)
        try:
            state=project_state()
            metadata=public_state(state,engine,observe=acquired)
            if action=='status':return metadata
            return {'metadata':metadata,'resources':resource_policy.snapshot(state,engine),
                    'modes':{row['map']:map_modes.mode_for(state,row) for row in state.get('worldPlan',{}).get('maps',[])},
                    'modeError':state.get('mapModeError'),'swapPolicy':state.get('memorySwap',{'enabled':False}),
                    'pendingMapMode':state.get('pendingMapMode'),'memoryBalancingEnabled':state.get('memoryBalancingEnabled',True)}
        finally:
            if acquired:LOCK.release()
    if action in {'tailscale.get','tailscale.set','tailscale.link'}:
        return tailscale_access.request(engine,project_state()['id'],STATE,CONFIG,action.split('.')[1],request.get('mode'),request.get('port',8088))
    with LOCK:
        state = project_state()
        if resume_running_only and (state.get('desiredState')!='running' or state.get('operation',{}).get('phase') not in {None,'completed'}):
            return public_state(state,engine)
        if action == 'status': return public_state(state, engine)
        if action == 'updates.progress':
            return update_progress.snapshot(state, engine, request.get('operationId'), request.get('includeOutput', False))
        # Turning chat Off must remove its listener even while a game command
        # or maintenance operation is in progress. This touches only DST's queue.
        if action == 'chat.queue.delete':return chat_queue(state,engine,'delete')
        if action == 'files.endpoint': return file_browser.endpoint(state, engine)
        if action == 'director.endpoint': return director_web.endpoint(state, engine)
        if action == 'regis.status': return regis_compatibility.status(state,engine)
        if action == 'regis.support': return regis_compatibility.support(state,engine)
        if action == 'memory-swap.status': return memory_swap_control.snapshot(state,engine)
        if action == 'assets.version': return installed_version()
        if action=='backups.schedule.get':return backup_schedule.snapshot(state,time.time(),bool(BACKUP_WORKER and BACKUP_WORKER.is_alive()))
        if action=='backups.history':return backup_schedule.history(state,request.get('recent',10))
        if action=='backups.jobs':return {'jobs':[{**row,'protected':row['id'] in protected_backup_jobs(state)} for row in engine.backup_jobs(state['id'])]}
        if action=='memory.policy':return {'enabled':state.get('memoryBalancingEnabled',True)}
        if action=='resources.get':return resource_policy.snapshot(state,engine)
        if action=='maps.management':return {'metadata':public_state(state,engine),'resources':resource_policy.snapshot(state,engine),
            'modes':{row['map']:map_modes.mode_for(state,row) for row in state.get('worldPlan',{}).get('maps',[])},'modeError':state.get('mapModeError'),
            'swapPolicy':state.get('memorySwap',{'enabled':False}),'pendingMapMode':state.get('pendingMapMode'),
            'memoryBalancingEnabled':state.get('memoryBalancingEnabled',True)}
        if action=='scale.get':
            if not state.get('worldId') or not state.get('worldPlan'):raise ValueError('The world is not prepared.')
            return scale_snapshot(state,read_template(),(STATE/'dune-app.password').read_text())
        if action=='maps.policy':return map_policy(state,engine)
        if action=='world-restart.status':return world_restart.snapshot(state)
        if action=='world-restart.research-audit':return world_research.audit(world_restart.NativeWorldRestart(state,engine,sys.modules[__name__]).sql,state.get('worldRestart',{}).get('researchSnapshot'))
        if state.get('operation',{}).get('phase')=='running':
            raise OperationBusyError('Another server operation is in progress.')
        if state.get('restore',{}).get('phase') in {'stopping','preparing','restoring','recovering','recovery-required'} and action not in {'updates.recover','world-restart.recover','world-restart.research-recover','logs.export'}:
            raise ValueError('Resolve the interrupted database restore before starting another operation.')
        if state.get('updateRun') and state['updateRun']['phase'] not in world_update.TERMINAL and action not in {'updates.recover','logs.export'}:
            raise ValueError('Recover the interrupted server update before starting another operation.')
        if state.get('worldRestart',{}).get('phase','done') not in world_restart.TERMINAL and action not in {'world-restart.recover','logs.export'}:
            raise ValueError('Recover the interrupted World Restart before starting another operation.')
        if state.get('worldResearchRecovery',{}).get('phase','completed') not in {'completed','rolled-back','failed-preflight'} and action not in {'world-restart.research-recover','logs.export'}:
            raise ValueError('Recover the interrupted research operation before starting another operation.')
        if state.get('pendingMemoryChange') and action!='maps.memory':raise ValueError('Finish the pending map memory allocation first.')
        if state.get('pendingMapMode') and action not in {'maps.mode','services.stop','logs.export'}:raise ValueError('Retry the pending map mode before another server operation.')
        if state.get('pendingResourceChange') and action!='resources.set':raise ValueError('Finish the pending resource allocation first.')
        if state.get('pendingSwapChange') and action not in {'memory-swap.set','memory-swap.recover','services.stop','logs.export'}:
            raise ValueError('Retry or restore the pending Memory Swap change before another server operation.')
        if state.get('pendingRegisChange') and action not in {'regis.set','regis.recover','services.stop','logs.export'}:
            raise ValueError('Finish or restore the pending Tank change in Server Settings before another server operation.')
        if state.get('backupCleanup') and action in {'backups.create','backups.verify','backups.restore','backups.delete','backups.import','backups.schedule.recover','updates.apply','updates.recover','database.migrate','world-restart.apply','world-restart.rollback','world-restart.research'}:
            raise ValueError('Finish or recover the pending backup cleanup before using backup or database maintenance controls.')
        if action=='backups.schedule.set':
            backup_schedule.configure(state,request,time.time());state.pop('backupSchedulerError',None);save(state)
            return backup_schedule.snapshot(state,time.time(),bool(BACKUP_WORKER and BACKUP_WORKER.is_alive()))
        if action=='backups.mirror.set':
            backup_mirror_control.configure(state,engine,save,request.get('enabled'));return backup_mirror_control.snapshot(state,engine)
        if action=='backups.mirror.cancel':
            backup_mirror_control.cancel_failed(state,engine,save);return backup_mirror_control.snapshot(state,engine)
        if action=='backups.jobs.prune':return prune_backup_jobs(state,engine,request.get('keepLast',10),request.get('keepDays',0))
        if action == 'files.open':
            prepare_file_browser(state, engine)
            return file_browser.endpoint(state, engine)
        if action == 'files.write-access': return file_browser.endpoint(state, engine)
        if action == 'director.write-access':
            if state.get('desiredState')!='running':raise ValueError('Start the battlegroup before using Director controls.')
            return director_web.endpoint(state,engine)
        if action=='resources.set':return set_resources(state,engine,request)
        if action=='memory.policy.set':
            if type(request.get('enabled')) is not bool:raise ValueError('Supply a JSON boolean for memory balancing.')
            if not request['enabled']:
                source=read_template()['world']['spec']['utilities']['director']['spec']['configFiles']['files']['director.ini']
                state['classicAutomaticMaps']=classic_automatic_maps(source)
            state['memoryBalancingEnabled']=request['enabled'];save(state)
            return {'enabled':state['memoryBalancingEnabled']}
        if action=='maps.memory':return set_map_memory(state,engine,request.get('map'),request.get('memoryGiB'))
        if action=='scale.patch':return request_scale(state,engine,request.get('name'),request.get('patch'))
        if action=='maps.floor':return set_map_floor(state,engine,request.get('map'),request.get('enabled'))
        if action=='maps.mode':return set_map_mode(state,engine,request.get('map'),request.get('mode'))
        if action=='maps.party-sharing':return set_party_sharing(state,engine,request.get('map'),request.get('shared'))
        if action in {'chat.queue.declare','chat.queue.delete','chat.queue.drain'}:
            return chat_queue(state,engine,action.rsplit('.',1)[1],request.get('maximum',25))
        if action=='settings.read':return read_settings(state,engine,request.get('file'))
        if action in {'map-settings.read','map-settings.write'}:
            target=request.get('target')
            if target=='global':
                key=request.get('file')
                if action.endswith('.write'):
                    if request.get('inherit'):raise ValueError('Global defaults cannot inherit another map file.')
                    current=read_settings(state,engine,key)
                    result=write_settings(state,engine,{'file':key,'raw':request.get('raw'),'revision':request.get('revision'),'expectedExists':current['fileExists']})
                else:result=read_settings(state,engine,key)
                timestamp=state.get('globalSettingsPending',{}).get(key)
                games=[engine.assert_owned(entry['id'],state['id'],component) for component,entry in state.get('services',{}).items() if component.startswith('game-')]
                running=any(game.get('State',{}).get('Status')=='running' for game in games)
                pending=bool(timestamp and (not games or any(settings_pending(timestamp,game) for game in games)))
                return {**result,'target':'global','overridden':False,'pendingRestart':pending,'adapterReady':True,'running':running}
            if not isinstance(target,str) or not re.fullmatch(r'[1-9][0-9]{0,5}',target) or not any(str(row['partition'])==target for row in state.get('worldPlan',{}).get('games',[])):
                raise ValueError('Choose a map partition from this world.')
            game=next(row for row in state['worldPlan']['games'] if str(row['partition'])==target)
            if not re.fullmatch(r'(?:Survival|DeepDesert)_[1-9][0-9]*',game.get('map','')):
                raise ValueError('Gameplay settings can be scoped only to Hagga and Deep Desert maps. Use Global defaults for the shared file.')
            if request.get('file') != 'server':
                raise ValueError('Per-map settings support only Custom Server Settings. Use Global for Game.ini and Engine.ini.')
            payload={key:request.get(key) for key in ('target','file','revision','raw','inherit') if key in request}
            payload['action']='maps.read' if action.endswith('.read') else 'maps.write'
            entry=state.get('services',{}).get('game-'+target)
            observed=engine.assert_owned(entry['id'],state['id'],'game-'+target) if entry else None
            supported=not observed or 'DST_MAP_SETTINGS_VERSION=1' in observed.get('Config',{}).get('Env',[])
            if action.endswith('.write') and not supported:
                raise ValueError('Update this map adapter before saving per-map settings. Existing settings were preserved.')
            result=settings_request(state,engine,payload)
            if action.endswith('.write') and result.get('changed'):
                state.setdefault('mapSettingsPending',{})[target]=time.time();save(state)
            local=state.get('mapSettingsPending',{}).get(target)
            inherited=0 if result.get('overridden') else state.get('globalSettingsPending',{}).get(request.get('file'),0)
            pending=settings_pending(max(local or 0,inherited or 0),observed)
            if local and not settings_pending(local,observed):
                state['mapSettingsPending'].pop(target,None);save(state)
            return {**result,'pendingRestart':bool(pending),'adapterReady':supported,
                    'running':bool(observed and observed['State'].get('Status')=='running')}
        if action in {'settings.backups.list','settings.backups.inspect','settings.backups.read','settings.backups.delete-checked'}:
            payload={'action':action.removeprefix('settings.')}
            if action=='settings.backups.read':payload.update(path=request.get('path'),sha256=request.get('sha256'))
            if action=='settings.backups.delete-checked':payload['files']=request.get('files')
            return settings_request(state,engine,payload)
        if action=='settings.write':return write_settings(state,engine,request)
        if action=='settings.startup':return set_startup_settings(state,engine,request.get('values'))
        if action=='settings.defaults':return engine.read_game_defaults(state['services']['game-1']['id'],state['id'])
        if action=='settings.delete-backups':
            reply=settings_client.request({'action':'backups.delete','paths':request.get('paths')})
            if not reply.get('ok'):raise ValueError(reply.get('error','Settings backups could not be deleted.'))
            return reply['data']
        if action=='settings.backup':
            reply=settings_client.request({'action':'backups.create','files':request.get('files')})
            if not reply.get('ok'):raise ValueError(reply.get('error','Settings backups could not be created.'))
            return reply['data']
        if action in {'network.set','memory-swap.set','memory-swap.recover','database.create','database.initialize','database.migrate','database.start','database.stop','world.configure','world.rename','connections.prepare',
                      'services.prepare','services.start','services.stop','services.restart','services.refresh-core-adapters','scale.prepare','maps.start','maps.stop','maps.restart','maps.observers.prepare','files.prepare','settings.prepare','regis.set','regis.recover','logs.export','updates.stage','updates.apply','updates.recover','rmq.publish','rmq.courier','games.refresh-adapters','backups.create','backups.verify','backups.restore','backups.delete','backups.cleanup.recover','backups.export','backups.import','backups.schedule.recover','backups.mirror.sync','backups.mirror.recover','world-restart.apply','world-restart.recover','world-restart.rollback','world-restart.research','world-restart.research-recover'}:
            if action=='memory-swap.set':memory_swap.validate(request)
            if action=='network.set':network_profile(state,request)
            if action=='memory-swap.recover' and (type(request.get('restorePrevious',False)) is not bool or request.get('confirmation')!='RECOVER MEMORY SWAP'):
                raise ValueError('Confirm Memory Swap recovery and supply a JSON boolean for restoring its previous policy.')
            if action in {'world-restart.apply','world-restart.rollback'} and request.get('confirmation')!=('RESTART WORLD' if action=='world-restart.apply' else 'ROLL BACK WORLD'):
                raise ValueError('Supply the exact World Restart confirmation.')
            if action=='world-restart.research' and request.get('confirmation')!='RESET RESEARCH':raise ValueError('Supply the exact research recovery confirmation.')
            if action=='regis.set' and (type(request.get('enabled')) is not bool or type(request.get('acknowledgeStoredTanks',False)) is not bool):
                raise ValueError('Supply JSON booleans for Tank support and the stored-Tank acknowledgement.')
            if action=='updates.apply' and (not isinstance(request.get('expectedBuild'),str) or not re.fullmatch(r'[0-9]{1,18}',request['expectedBuild']) or type(request.get('allowOnline',False)) is not bool or type(request.get('withTanks',False)) is not bool):raise ValueError('Supply a valid build and JSON boolean online-player and Tank authorization.')
            if 'publishGateway' in request and (action!='services.start' or type(request['publishGateway']) is not bool):raise ValueError('Only a typed start can select gateway publication.')
            if action=='logs.export' and request.get('scope') not in {'battlegroup','operator','diagnostics'}:raise ValueError('Choose battlegroup, operator or diagnostics logs.')
            if action in {'network.set','updates.apply','updates.recover','database.migrate','database.initialize','services.restart','world-restart.apply','world-restart.rollback','world-restart.research'} and any(
                entry.get('phase') in {'preparing','running'} or entry.get('verification',{}).get('phase') in {'preparing','running'}
                for entry in state.get('backups',{}).values()):
                raise OperationBusyError('Wait for the active backup or restore rehearsal before database maintenance.')
            if 'requestId' in request:
                if action not in {'services.restart','updates.apply'} or not isinstance(request['requestId'],str) or not re.fullmatch(r'[a-f0-9]{32}',request['requestId']):
                    raise ValueError('Invalid scheduled maintenance request identity.')
                if any(entry.get('phase') in {'preparing','running'} or entry.get('verification',{}).get('phase') in {'preparing','running'} for entry in state.get('backups',{}).values()):
                    raise OperationBusyError('A backup or restore rehearsal is still running.')
            state['operation']={'id':uuid.uuid4().hex,'action':action,'phase':'running','startedAt':time.time()}
            if action=='network.set':state['operation'].update(stage='stopping',targetAddress=request['address'],targetMode=request['mode'],resume=state.get('desiredState')=='running')
            if action=='updates.apply':state['operation']['withTanks']=request.get('withTanks',False)
            if 'requestId' in request:
                state['operation']['requestId']=request['requestId']
                if action=='updates.apply':state['operation']['expectedBuild']=request['expectedBuild']
            if action=='maps.restart':state['operation']['partition']=request.get('partition')
            save(state)
            # Persist before dispatch. Browser disconnects do not cancel an
            # already-authorized operation or trigger duplicate provisioning.
            result=public_state(state,engine)
            threading.Thread(target=run_operation,args=(state,engine,request),daemon=True).start()
            return result
        if action == 'credentials.save':
            token = request.get('token')
            if not isinstance(token,str) or not 20 <= len(token) <= 8192 or any(c in token for c in '\r\n\x00'):
                raise ValueError('Enter a valid Funcom service token.')
            try:
                parts=token.split('.')
                if len(parts)!=3: raise ValueError()
                claims=json.loads(base64.urlsafe_b64decode(parts[1]+'='*((-len(parts[1]))%4)))
                host_id=claims['HostId'].lower()
                if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,52}',host_id): raise ValueError()
            except (ValueError,KeyError,TypeError,AttributeError):
                raise ValueError('The token does not contain a supported self-host HostId.') from None
            if state.get('hostId') and state['hostId']!=host_id:
                raise ValueError('This token belongs to a different self-host identity; existing services were preserved.')
            if state.get('services'):
                raise ValueError('Stop and update the prepared game services before replacing their token.')
            atomic(STATE / 'funcom-token', token)
            return public_state(state, engine)
        raise ValueError('Unsupported Docker management action.')


def authorize_peer(uid,action):
    if uid not in {0,10001,10002} or uid==10002 and action not in {'scale.get','scale.patch'}:
        raise ValueError('This service identity cannot perform that operation.')


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(40)
        try:
            raw = self.rfile.readline(4*1024*1024+1)
            request=json.loads(raw)
            limit=4*1024*1024 if request.get('action') in {'settings.write','settings.startup','map-settings.write'} else 256*1024 if request.get('action')=='settings.backups.delete-checked' else 65536
            if len(raw)>limit: raise ValueError('Management request exceeds its limit.')
            _,uid,_=struct.unpack('3i',self.connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            authorize_peer(uid,request.get('action'))
            response = {'ok':True, 'data':dispatch(request)}
        except OperationBusyError as error:response={'ok':False,'code':'operation-busy','error':str(error)}
        except (ValueError, EngineError) as error: response={'ok':False,'error':str(error)}
        except Exception: response={'ok':False,'error':'Docker management request failed. Existing server data was preserved.'}
        try:self.wfile.write(json.dumps(response).encode('utf-8')+b'\n')
        except (BrokenPipeError,ConnectionResetError):pass


class ManagementServer(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):
    daemon_threads=True


def resume_interrupted_update(state,engine):
    try:
        world_update.NativeUpdate(state,engine,sys.modules[__name__]).recover()
        success=state['updateRun']['phase']=='completed'
        state['operation'].update(phase='completed' if success else 'failed',finishedAt=time.time())
        if not success:state['operation']['error']=('The interrupted server update ended before changing the world.' if state['updateRun']['phase']=='failed-preflight' else 'The interrupted server update was rolled back to the previous version.')
    except Exception:
        state['updateRun']['phase']='recovery-required'
        state['operation'].update(phase='failed',error='Server update recovery needs review. The maintenance guard and previous resources were retained.',finishedAt=time.time())
    finally:save(state)


def resume_interrupted_world_restart(state,engine):
    try:
        world_restart.NativeWorldRestart(state,engine,sys.modules[__name__]).recover()
        state['operation'].update(phase='completed',finishedAt=time.time())
    except Exception:
        state['worldRestart']['phase']='recovery-required'
        state['operation'].update(phase='failed',error='World Restart recovery needs review. Game access remains blocked and backups were preserved.',finishedAt=time.time())
    finally:save(state)


def resume_interrupted_world_research(state,engine):
    try:
        world_research.NativeResearchRecovery(state,engine,sys.modules[__name__]).recover()
        state['operation'].update(phase='completed',finishedAt=time.time())
    except Exception:
        state['worldResearchRecovery']['phase']='recovery-required'
        state['operation'].update(phase='failed',error='Research recovery needs review. Game access remains blocked and backups were preserved.',finishedAt=time.time())
    finally:save(state)


def resume_requested_services(engine):
    """Recover saved running intent once per manager boot through normal guards."""
    try:
        with LOCK:
            state=project_state()
            if state.get('desiredState')!='running' or not state.get('worldPlan') or not state.get('services'):
                return False
            if state.get('operation',{}).get('phase') not in {None,'completed'}:
                return False
            initial={p for row in state['worldPlan']['maps'] for p in row['partitions'][:row['initialReplicas']]}
            required=[(name,row) for name,row in state.get('connections',{}).items()]
            for name,row in state['services'].items():
                if name.startswith('game-'):
                    default='running' if int(name[5:]) in initial else 'stopped'
                    if state.get('mapTargets',{}).get(name,default)!='running':continue
                required.append((name,row))
            if all(engine.assert_owned(row['id'],state['id'],name)['State']['Status']=='running' for name,row in required):
                return False
        # Dispatch re-reads persisted state and enforces pending-change, resource,
        # migration and recovery guards instead of starting containers directly.
        dispatch({'action':'services.start'},engine,resume_running_only=True)
        return True
    except Exception as exc:
        with LOCK:
            state=project_state()
            state['startupRecoveryError']=str(exc)
            save(state)
        return False


if __name__ == '__main__':
    recovered=project_state()
    restoring=False
    updating=False
    restarting_world=False
    recovering_research=False
    if recovered.get('operation',{}).get('phase')=='running':
        restoring=recovered['operation'].get('action')=='backups.restore' and recovered.get('restore')
        updating=recovered['operation'].get('action') in {'updates.apply','updates.recover'} and recovered.get('updateRun') and recovered['updateRun']['phase'] not in world_update.TERMINAL
        restarting_world=recovered['operation'].get('action') in {'world-restart.apply','world-restart.recover','world-restart.rollback'} and recovered.get('worldRestart') and recovered['worldRestart']['phase'] not in world_restart.TERMINAL
        recovering_research=recovered['operation'].get('action') in {'world-restart.research','world-restart.research-recover'} and recovered.get('worldResearchRecovery') and recovered['worldResearchRecovery']['phase'] not in {'completed','rolled-back','failed-preflight'}
        if recovered['operation'].get('action')=='scale.apply':recover_interrupted_scale(recovered,Engine())
        if recovered.get('updateRun',{}).get('phase')=='completed' and recovered['operation'].get('action') in {'updates.apply','updates.recover'}:
            recovered['operation'].update(phase='completed',finishedAt=time.time())
        elif (recovered['operation'].get('action') in {'world-restart.apply','world-restart.recover','world-restart.rollback'} and
              recovered.get('worldRestart',{}).get('activeOperationId',recovered.get('worldRestart',{}).get('id'))==recovered['operation']['id'] and
              recovered.get('worldRestart',{}).get('phase') in world_restart.TERMINAL):recovered['operation'].update(phase='completed',finishedAt=time.time())
        elif (recovered['operation'].get('action') in {'world-restart.research','world-restart.research-recover'} and
              recovered.get('worldResearchRecovery',{}).get('activeOperationId',recovered.get('worldResearchRecovery',{}).get('id'))==recovered['operation']['id'] and
              recovered.get('worldResearchRecovery',{}).get('phase') in {'completed','rolled-back','failed-preflight'}):recovered['operation'].update(phase='completed',finishedAt=time.time())
        elif not restoring and not updating and not restarting_world and not recovering_research:recovered['operation'].update(phase='interrupted',error='The management service restarted during this operation. Review its component states before retrying.')
        save(recovered)
    if restoring:threading.Thread(target=resume_interrupted_restore,args=(recovered,Engine()),daemon=True).start()
    if updating:threading.Thread(target=resume_interrupted_update,args=(recovered,Engine()),daemon=True).start()
    if restarting_world:threading.Thread(target=resume_interrupted_world_restart,args=(recovered,Engine()),daemon=True).start()
    if recovering_research:threading.Thread(target=resume_interrupted_world_research,args=(recovered,Engine()),daemon=True).start()
    tailscale_access.resume(Engine(),recovered['id'],STATE,CONFIG)
    SOCKET.parent.mkdir(parents=True, exist_ok=True)
    if SOCKET.exists(): SOCKET.unlink()
    server = ManagementServer(str(SOCKET), Handler)
    os.chown(SOCKET, -1, 10001)
    SOCKET.chmod(0o660)
    BACKUP_WORKER=threading.Thread(target=run_backup_scheduler,name='DuneBackupScheduler',daemon=True)
    BACKUP_WORKER.start()
    threading.Thread(target=run_map_mode_scheduler,name='DuneMapModeScheduler',daemon=True).start()
    threading.Thread(target=resume_requested_services,args=(Engine(),),name='DuneStartupRecovery',daemon=True).start()
    server.serve_forever()
