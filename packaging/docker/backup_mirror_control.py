"""Persistent mirror coordination. Copies only; never starts databases or maps."""
import time,uuid
from engine import EngineError

def protected_ids(state):
    config=state.get('backupMirror',{});run=config.get('run',{})
    result=set(run.get('backupIds',[])) if run.get('phase') in {'preparing','running','failed'} else set()
    if config.get('enabled'):
        for key,row in state.get('backups',{}).items():
            if row.get('phase')=='completed' and config.get('mirrored',{}).get(row['name'],{}).get('sha256')!=row.get('sha256'):result.add(key)
    return result

def snapshot(state,engine):
    config=state.get('backupMirror',{});run=config.get('run',{})
    try:
        target=engine.mirror_destination() if hasattr(engine,'mirror_destination') else {}
        if not isinstance(target,dict):target={}
        error=config.get('error') or run.get('error') or ''
    except (ValueError,EngineError,OSError):target={};error='The configured host backup folder needs review.'
    return {'enabled':config.get('enabled',False),'available':target.get('available',False),
            'folder':target.get('folder','')+('/world-'+state['id'] if target.get('folder') else ''),
            'phase':run.get('phase','idle'),'error':error,'lastCopiedAt':config.get('lastCopiedAt'),
            'copiedCount':run.get('copiedCount',0),'protectedBackups':len(protected_ids(state))}

def observe(state,engine,save):
    config=state.get('backupMirror',{});run=config.get('run',{})
    if run.get('phase')!='running':return
    try:observed=engine.assert_owned(run['job'],state['id'],'db-mirror')
    except EngineError:
        run.update(phase='failed',error='The recorded mirror job is unavailable and needs review. Existing copies were preserved.');save(state);return
    if observed['State']['Status']!='exited':return
    try:report=engine.backup_report(run['job'],state['id'],'db-mirror')
    except EngineError:report={}
    expected={row['name']:(row['sha256'],row['bytes']) for row in run['files']}
    actual=report.get('files',[])
    valid=(observed['State'].get('ExitCode')==0 and report.get('ok') is True and report.get('mode')=='mirror' and
           report.get('id')==run['id'] and report.get('attempt')==run['attempt'] and report.get('project')==state['id'] and
           isinstance(actual,list) and len(actual)==len(expected) and
           all(isinstance(row,dict) and type(row.get('copied')) is bool for row in actual))
    if valid:valid={row.get('name'):(row.get('sha256'),row.get('bytes')) for row in actual}==expected
    run.update(phase='completed' if valid else 'failed',finishedAt=time.time())
    if valid:
        for row in actual:config.setdefault('mirrored',{})[row['name']]={'sha256':row['sha256'],'bytes':row['bytes'],'copiedAt':time.time()}
        run['copiedCount']=sum(row['copied'] for row in actual);config['lastCopiedAt']=time.time();config.pop('error',None);run.pop('error',None)
    else:run['error']='Backup mirroring needs review. Existing copies and source backups were preserved.'
    save(state)

def start(state,engine,save,retry=False,check_all=False):
    if state.get('backupCleanup'):return
    config=state.setdefault('backupMirror',{'enabled':False,'mirrored':{}});run=config.get('run')
    if retry:
        if not run or run.get('phase')!='failed':raise ValueError('There is no failed mirror batch to retry.')
        if run.get('job') and engine.assert_owned(run['job'],state['id'],'db-mirror')['State']['Status']!='exited':raise ValueError('The previous mirror job must finish before retrying.')
        if run['attempt']>=100:raise ValueError('This mirror batch needs deployment review before another retry.')
        run.update(attempt=run['attempt']+1,phase='preparing',startedAt=time.time());run.pop('error',None);config.pop('error',None);save(state)
    if run and run.get('phase')=='failed':return
    if not run or run.get('phase') not in {'preparing','running'}:
        if not config.get('enabled'):return
        rows=[(key,row) for key,row in state.get('backups',{}).items() if row.get('phase')=='completed' and
              (check_all or config.get('mirrored',{}).get(row['name'],{}).get('sha256')!=row.get('sha256'))]
        rows.sort(key=lambda pair:pair[1]['createdAt'],reverse=True)
        if not rows:return
        selected=rows[:100]
        run={'id':uuid.uuid4().hex,'attempt':0,'phase':'preparing','startedAt':time.time(),
             'backupIds':[key for key,row in selected],'files':[{key:row[key] for key in ('name','sha256','bytes')} for _,row in selected]}
        config['run']=run;save(state)
    identifier=engine.create_backup_mirror_job(state['id'],{key:run[key] for key in ('id','attempt','files')})
    run.update(job=identifier,phase='running');save(state)
    status=engine.assert_owned(identifier,state['id'],'db-mirror')['State']['Status']
    if status=='created':engine.lifecycle(identifier,state['id'],'start')
    elif status not in {'running','exited'}:raise ValueError('The mirror copy job needs review.')

def configure(state,engine,save,enabled):
    if type(enabled) is not bool:raise ValueError('Supply a JSON boolean for backup mirroring.')
    if enabled and not engine.mirror_destination().get('available'):raise ValueError('Prepare the host backup folder with the DST launcher before enabling mirroring.')
    config=state.setdefault('backupMirror',{'enabled':False,'mirrored':{}});config['enabled']=enabled;save(state)

def cancel_failed(state,engine,save):
    config=state.get('backupMirror',{});run=config.get('run',{})
    if run.get('phase')!='failed':raise ValueError('Only a failed mirror attempt can be cancelled.')
    if run.get('job') and engine.assert_owned(run['job'],state['id'],'db-mirror')['State']['Status']!='exited':raise ValueError('The mirror job must be stopped before cancelling its retry.')
    config['enabled']=False;config.pop('error',None);run.update(phase='cancelled',finishedAt=time.time());run.pop('error',None);save(state)

def tick(state,engine,save):
    config=state.get('backupMirror',{});run=config.get('run',{})
    if not config.get('enabled') and run.get('phase') not in {'preparing','running'}:return
    try:
        observe(state,engine,save)
        run=config.get('run',{})
        if run.get('phase')=='running' and engine.assert_owned(run['job'],state['id'],'db-mirror')['State']['Status']!='created':return
        start(state,engine,save)
    except (ValueError,EngineError,OSError):
        config['error']='The backup mirror needs review. Original backups and existing copies were preserved.'
        if config.get('run'):config['run']['phase']='failed'
        save(state)
