"""Same-world reset composed from fresh schema, backup rehearsal and restore.

No volume deletion. Recovery keeps game access fenced until the exact recorded
database operation is resolved. A published world is never automatically reset
back over possible new gameplay.
"""
import json,time,uuid
from pathlib import Path
from world_update import NativeUpdate
from world_template import read_template,fresh_partition_sql

TERMINAL={'done','rolled-back','failed-preflight'}

class NativeWorldRestart(NativeUpdate):
    @property
    def run(self):return self.s['worldRestart']

    def phase(self,name,**values):
        self.run.update(phase=name,**values)
        self.run['activeOperationId']=self.s['operation']['id']
        steps=self.run.setdefault('steps',[])
        for step in steps:
            if step['status']=='running':step['status']='done'
        current=next((step for step in steps if step['id']==name),None)
        status='done' if name in TERMINAL|{'completed'} else 'failed' if name=='recovery-required' else 'running'
        if current:current['status']=status
        else:steps.append({'id':name,'label':name.replace('-',' ').capitalize(),'status':status,'detail':''})
        self.s['operation']['message']='World Restart: '+name.replace('-',' ')
        self.m.save(self.s)

    def assert_offline(self):
        status=self.m.public_state(self.s,self.e)
        for row in status['services']:
            if not row['component'].startswith('game-') or row.get('state') in {'created','exited'}:continue
            if row.get('state')!='running' or row.get('players')!=0 or row.get('heartbeatAt',0)<time.time()-90:
                raise ValueError('Every player must be offline and running maps must have fresh occupancy reports before World Restart.')

    def assert_stopped(self):
        for key,row in self.s.get('services',{}).items():
            if self.e.assert_owned(row['id'],self.s['id'],key)['State']['Status'] not in {'created','exited'}:
                raise ValueError('Every battlegroup service must finish stopping before database replacement.')

    def gameplay_count(self):
        return int(self.sql('SELECT (SELECT count(*) FROM dune.player_state)+(SELECT count(*) FROM dune.actors)+(SELECT count(*) FROM dune.accounts)'))

    def fresh_archive(self):
        if not self.run.get('freshOperation'):
            self.phase('preparing-fresh-schema',freshOperation=uuid.uuid4().hex,
                       freshName=self.m.next_backup_name(self.s,time.time()),freshBackupId=uuid.uuid4().hex)
        image=next(tag for item in self.m.assets_state()['images'] if item['archive']=='battlegroup/server-db-utils.tar' for tag in item['tags'])
        template=read_template()
        if template['sha256']!=self.run['templateSha256']:raise ValueError('The installed official template changed during World Restart.')
        script='PARTITION_SQL = '+repr(fresh_partition_sql(template['partitions']))+'\n'+Path('/opt/dst-manager/fresh-world-job.py').read_text()
        job=self.e.create_migration_job(self.s['id'],image,self.s['database']['network'],self.state_volume(),self.s['database']['name'],
            script,'dst-'+self.s['id']+'-backups',self.run['freshName'],operation=self.run['freshOperation'])
        self.phase('preparing-fresh-schema',freshJob=job)
        observed=self.owned_job(job,'db-migrate')
        if observed['State']['Status']=='created':self.e.lifecycle(job,self.s['id'],'start')
        try:self.wait_job(job,'db-migrate')
        finally:
            if self.owned_job(job,'db-migrate')['State']['Status']=='exited':self.demote()
        report=self.e.backup_report(job,self.s['id'],'db-migrate')
        if (report.get('ok') is not True or report.get('mode')!='fresh-world' or report.get('operationId')!=self.run['freshOperation'] or
            report.get('name')!=self.run['freshName'] or report.get('stagingDatabaseRemoved') is not True or
            report.get('restored',{}).get('players')!=0 or report.get('restored',{}).get('partitions')!=len(template['partitions'])):
            raise ValueError('The fresh-world schema archive did not verify. The existing world was retained.')
        entry=self.s.setdefault('backups',{}).setdefault(self.run['freshBackupId'],{
            'name':report['name'],'phase':'completed','sha256':report['sha256'],'bytes':report['bytes'],
            'createdAt':self.run['startedAt'],'finishedAt':time.time(),'purpose':'fresh-world-template','operationId':self.run['id']})
        if entry.get('verification',{}).get('phase')!='completed':
            self.phase('verifying-fresh-schema');self.m.start_backup(self.s,self.e,self.run['freshBackupId'])
            self.wait_job(entry['verification']['job'],'db-verify');self.m.observe_backup_jobs(self.s,self.e)
        if entry.get('verification',{}).get('phase')!='completed' or entry['verification']['restored']!=report['restored']:
            raise ValueError('The fresh-world archive failed its independent restore rehearsal.')

    def publish(self,phase):
        # A publication intent is durable before any game can write. From this
        # point recovery may finish startup, never restore a pre-reset archive.
        self.phase('publishing',committed=True)
        if self.run['previousDesired']=='running':
            self.m.start_services(self.s,self.e,publish_gateway=False);self.ready(False)
            self.m.start_services(self.s,self.e);self.ready(True)
        self.maintenance(False)
        if phase in {'done','completed'}:self.run.pop('error',None)
        self.phase(phase,finishedAt=time.time())

    def apply(self,confirmation):
        if confirmation!='RESTART WORLD':raise ValueError('Type RESTART WORLD exactly to confirm this world reset.')
        if self.s['phase']!='database-ready' or not self.s.get('worldId') or not self.s.get('worldPlan'):
            raise ValueError('Finish preparing this battlegroup before World Restart.')
        if self.s.get('worldRestart',{}).get('phase','done') not in TERMINAL:raise ValueError('Recover the previous World Restart before another reset.')
        if self.s.get('generationChange') or self.s.get('pendingAddressChange'):raise ValueError('Finish the pending server configuration first.')
        status=self.m.public_state(self.s,self.e)
        if status.get('database',{}).get('state')!='running' or status.get('database',{}).get('health')!='healthy':raise ValueError('Start the database and wait for healthy status before World Restart.')
        if self.s.get('backupCleanup') or any(row.get('phase') in {'preparing','running'} or row.get('verification',{}).get('phase') in {'preparing','running'} for row in self.s.get('backups',{}).values()):raise ValueError('Wait for backup and cleanup operations before World Restart.')
        if self.s.get('worldResearchRecovery',{}).get('phase','completed') not in {'completed','rolled-back','failed-preflight'}:raise ValueError('Resolve the research recovery before starting another World Restart.')
        if self.s.get('worldRestart'):self.s.setdefault('worldRestartHistory',[]).append(self.s['worldRestart'])
        self.assert_offline()
        template=read_template()
        self.s['worldRestart']={'id':self.s['operation']['id'],'world':self.s['worldId'],'phase':'preflight','startedAt':time.time(),
            'previousDesired':self.s.get('desiredState','stopped'),'templateSha256':template['sha256'],'committed':False}
        self.m.save(self.s)
        try:
            self.maintenance(True);self.assert_offline();self.phase('stopping',stopStarted=True)
            self.m.stop_services(self.s,self.e);self.assert_stopped()
            self.phase('capturing-research')
            import world_research
            self.run['researchSnapshot']=world_research.capture(self.sql);self.m.save(self.s)
            self.backup();self.fresh_archive();self.assert_stopped()
            self.phase('replacing-database',promotionStarted=True)
            self.m.restore_backup(self.s,self.e,self.run['freshBackupId'],'RESTORE',keep_maintenance=True)
            self.phase('verifying-empty-world')
            if self.gameplay_count()!=0:raise ValueError('Unexpected gameplay records appeared before world publication.')
            self.publish('done')
        except Exception as error:
            self.run['error']=str(error);self.m.save(self.s)
            try:self.recover()
            except Exception:
                self.phase('recovery-required');raise ValueError('World Restart needs recovery. Keep players offline; the backup and previous database were preserved.') from error
            if self.run['phase']=='done':return
            raise

    def recover(self):
        if self.run['phase'] in TERMINAL:raise ValueError('There is no interrupted World Restart to recover.')
        self.maintenance(True)
        if self.run.get('committed'):
            self.publish(self.run.get('completionPhase','done'));return
        job=self.run.get('freshJob')
        if job:
            observed=self.owned_job(job,'db-migrate')
            if observed['State']['Status']=='running':self.wait_job(job,'db-migrate',success=False)
            elif observed['State']['Status']=='created':
                # A prepared job has not elevated or initialized anything.
                self.e.lifecycle(job,self.s['id'],'start');self.wait_job(job,'db-migrate',success=False)
            self.demote()
        self.m.stop_services(self.s,self.e);self.assert_stopped()
        if self.run.get('promotionStarted'):
            restore=self.s.get('restore',{})
            if restore.get('phase') in {'restoring','recovering','recovery-required'} and restore.get('job'):
                try:self.m.finish_restore(self.s,self.e)
                except Exception:
                    if restore.get('phase')=='recovery-required':raise
            if restore.get('phase')=='recovery-required':raise ValueError('Resolve the recorded database rename before further recovery.')
            self.phase('restoring-rollback-backup')
            self.m.restore_backup(self.s,self.e,self.run['backupId'],'RESTORE',keep_maintenance=True)
            self.run['completionPhase']='rolled-back';self.publish('rolled-back')
        else:
            self.run['completionPhase']='failed-preflight';self.publish('failed-preflight')

    def rollback(self,confirmation):
        if confirmation!='ROLL BACK WORLD':raise ValueError('Type ROLL BACK WORLD exactly to confirm rollback.')
        if self.run.get('phase')!='done' or not self.run.get('backupId'):raise ValueError('There is no completed World Restart to roll back.')
        self.assert_offline()
        if self.gameplay_count()!=0:raise ValueError('This world has new gameplay records. Use the explicit Restore Backup review to replace newer progress.')
        self.run.update(phase='rollback-preflight',committed=False,promotionStarted=False,
                        previousDesired=self.s.get('desiredState','stopped'),completionPhase='rolled-back',activeOperationId=self.s['operation']['id'])
        self.m.save(self.s);self.maintenance(True)
        try:
            self.m.stop_services(self.s,self.e);self.assert_stopped()
            if self.gameplay_count()!=0:raise ValueError('Gameplay changed before rollback; no backup was restored.')
            self.phase('rolling-back',promotionStarted=True)
            self.m.restore_backup(self.s,self.e,self.run['backupId'],'RESTORE',keep_maintenance=True)
            self.publish('rolled-back')
        except Exception:
            self.phase('recovery-required');raise

def snapshot(state):
    run=state.get('worldRestart',{});research=state.get('worldResearchRecovery',{})
    phase=run.get('phase','idle');active=phase not in TERMINAL|{'idle','recovery-required'}
    backup=state.get('backups',{}).get(run.get('backupId'),{})
    research_active=research.get('phase','completed') not in {'completed','rolled-back','failed-preflight','recovery-required'}
    research_backup=state.get('backups',{}).get(research.get('backupId'),{})
    return {'phase':phase,'running':active,'world':run.get('world',''),
            'rollbackAvailable':phase=='done' and bool(backup),'backupPath':'/backups/'+backup['name'] if backup else '',
            'recoveryRequired':phase=='recovery-required' or research_active or research.get('phase')=='recovery-required','researchRecoveryRequired':research.get('phase')=='recovery-required',
            'researchRecoveryRunning':research_active,'researchRecoveryBackupPath':'/backups/'+research_backup['name'] if research_backup else '',
            'error':research.get('error','') if research_active or research.get('phase')=='recovery-required' else run.get('error',''),
            'steps':research.get('steps',[]) if research_active or research.get('phase')=='recovery-required' else run.get('steps',[]),
            'started':run.get('startedAt'),'finished':run.get('finishedAt')}
