"""Native update transaction, composed from the existing verified host adapters."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
import asset_updates
import service_generations
from core_services import service_specs,game_spec
from connection_services import queue_spec
from engine import EngineError
from game_plan import plan_world
from scale_protocol import native_director_ini,classic_automatic_maps
from world_template import read_template

TERMINAL={'completed','rolled-back','failed-preflight'}


def partition_upgrade_sql(rows):
    """Add new official partitions; retain existing bounds and manual pins."""
    commands=['BEGIN; SET LOCAL search_path TO dune,public;']
    for row in rows:
        name=row['map'].replace("'","''");identifier=int(row['id']);dimension=int(row['dimension'])
        commands.append("DO $$BEGIN IF EXISTS(SELECT 1 FROM dune.world_partition WHERE partition_id="+str(identifier)+" AND (map<>'"+name+"' OR dimension_index<>"+str(dimension)+")) THEN RAISE EXCEPTION 'Existing partition identity changed; review required'; END IF; END$$;")
        definition=json.dumps(row['definition'],separators=(',',':')).replace("'","''")
        commands.append("INSERT INTO dune.world_partition(partition_id,map,partition_definition,dimension_index,blocked) VALUES("+str(identifier)+",'"+name+"','"+definition+"'::jsonb,"+str(dimension)+","+('true' if row['blocked'] else 'false')+") ON CONFLICT(partition_id) DO NOTHING;")
    commands.append("SELECT setval('dune.world_partition_partition_id_seq',GREATEST((SELECT COALESCE(max(partition_id),1) FROM dune.world_partition),(SELECT last_value FROM dune.world_partition_partition_id_seq))); COMMIT;")
    return '\n'.join(commands)


class NativeUpdate:
    def __init__(self,state,engine,host):self.s=state;self.e=engine;self.m=host

    @property
    def run(self):return self.s['updateRun']

    def phase(self,name,**values):
        self.run.update(phase=name,**values)
        self.s['operation']['message']='Server update: '+name.replace('-',' ')
        self.m.save(self.s)

    def maintenance(self,active):
        self.m.atomic(self.m.CONFIG/'docker-maintenance.json',json.dumps({'active':active,'operation':self.run['id']}),0o640,10001)

    def owned_job(self,identifier,component):
        observed=self.e.request('GET','/containers/'+identifier+'/json',expected=(200,404))
        if not observed:raise ValueError('The recorded update job is missing; recovery is required.')
        labels=observed.get('Config',{}).get('Labels',{})
        if labels.get('io.dst.managed')!='true' or labels.get('io.dst.project')!=self.s['id'] or labels.get('io.dst.component')!=component:
            raise ValueError('The recorded update job identity changed; recovery stopped.')
        return observed

    def wait_job(self,identifier,component,success=True):
        while True:
            try:observed=self.owned_job(identifier,component)
            except (OSError,EngineError):
                # A daemon/transport outage is not evidence that a job ended.
                time.sleep(2);continue
            status=observed['State']['Status']
            if status in {'exited','dead'}:
                if success and (status!='exited' or observed['State'].get('ExitCode')!=0):raise ValueError('The '+component+' update job failed.')
                return observed
            if status=='created':raise ValueError('The recorded update job has not started; review or recover the operation.')
            time.sleep(1)

    def state_volume(self):
        own=self.e.inspect(os.environ['HOSTNAME'])
        return next(row['Name'] for row in own['Mounts'] if row.get('Type')=='volume' and row.get('Destination')=='/projects')

    def assets_volume(self):
        own=self.e.inspect(os.environ['HOSTNAME'])
        return next(row['Name'] for row in own['Mounts'] if row.get('Type')=='volume' and row.get('Destination')=='/assets')

    def switch(self,mode):
        key=mode+'Job';opkey=mode+'Operation'
        if opkey not in self.run:self.phase(self.run['phase'],**{opkey:uuid.uuid4().hex})
        operation=self.run[opkey]
        if key not in self.run:
            name='dst-'+self.s['id']+'-asset-'+mode+'-'+operation[:16]
            existing=self.e.request('GET','/containers/'+name+'/json',expected=(200,404))
            if existing:
                labels=existing.get('Config',{}).get('Labels',{})
                if labels.get('io.dst.operation')!=operation or labels.get('io.dst.stage')!=self.run['stageId']:
                    raise ValueError('The package job belongs to another update.')
                identifier=existing['Id']
            else:
                identifier=self.e.create_asset_activation_job(self.s['id'],operation,self.run['stageId'],self.run['build'],mode,self.assets_volume())
            self.phase(self.run['phase'],**{key:identifier})
        observed=self.owned_job(self.run[key],'asset-switch')
        if observed['State']['Status']=='created':self.e.lifecycle(self.run[key],self.s['id'],'start')
        self.wait_job(self.run[key],'asset-switch')
        journal=json.loads((Path('/assets/staged')/self.run['stageId']/'activation-state.json').read_text())
        expected='active' if mode=='activate' else 'rolled-back'
        if journal.get('stage')!=self.run['stageId'] or journal.get('phase')!=expected:raise ValueError('Package activation state could not be verified.')

    def demote(self):
        self.e.exec_internal(self.s['database']['id'],self.s['id'],'postgres',['psql','-X','-U','postgres','-d','postgres','-v','ON_ERROR_STOP=1','-c','ALTER ROLE dune NOSUPERUSER'])

    def sql(self,query):
        return self.e.exec_internal(self.s['database']['id'],self.s['id'],'postgres',['psql','-X','-U','dune','-d','dune','-v','ON_ERROR_STOP=1','-t','-A','-c',query]).strip()

    def backup(self):
        self.phase('backing-up')
        old=set(self.s.get('backups',{}));self.m.start_backup(self.s,self.e)
        created=set(self.s['backups'])-old
        if len(created)!=1:raise ValueError('The update backup identity could not be verified.')
        identifier=created.pop();self.phase('backing-up',backupId=identifier)
        entry=self.s['backups'][identifier]
        self.wait_job(entry['job'],'db-backup');self.m.observe_backup_jobs(self.s,self.e)
        if entry['phase']!='completed':raise ValueError('The fresh update backup failed.')
        self.phase('verifying-backup');self.m.start_backup(self.s,self.e,identifier)
        self.wait_job(entry['verification']['job'],'db-verify');self.m.observe_backup_jobs(self.s,self.e)
        if entry['verification']['phase']!='completed':raise ValueError('The fresh update backup did not pass restore verification.')

    def migrate(self):
        self.phase('migrating-schema',schemaMayHaveChanged=True)
        image=next(tag for item in self.m.assets_state()['images'] if item['archive']=='battlegroup/server-db-utils.tar' for tag in item['tags'])
        self.e.ensure_package_image('/assets/server/images/battlegroup/server-db-utils.tar',image)
        identifier=self.e.create_migration_job(self.s['id'],image,self.s['database']['network'],self.state_volume(),self.s['database']['name'],
            (Path('/opt/dst-manager')/'migration-job.py').read_text(),'dst-'+self.s['id']+'-backups','pre-update-schema-'+self.run['id'][:16]+'.dump',operation=self.run['id'])
        self.phase('migrating-schema',migrationJob=identifier)
        observed=self.owned_job(identifier,'db-migrate')
        if observed['State']['Status']=='created':self.e.lifecycle(identifier,self.s['id'],'start')
        try:self.wait_job(identifier,'db-migrate')
        finally:
            # Do not revoke privileges under a still-running migration. The
            # recovery path also settles the exact job before this demotion.
            observed=self.owned_job(identifier,'db-migrate')
            if observed['State']['Status'] in {'exited','dead'}:self.demote()
        report=self.e.backup_report(identifier,self.s['id'],'db-migrate')
        if report.get('operationId')!=self.run['id'] or report.get('exitCode')!=0 or not report.get('backupVerified') or report.get('roleElevated'):
            raise ValueError('The official migration report did not match this update.')
        if self.sql("SELECT rolsuper FROM pg_roles WHERE rolname='dune'")!='f':raise ValueError('The application database role is still elevated.')
        expected=self.s['backups'][self.run['backupId']]['verification']['restored']['players']
        if int(self.sql('SELECT count(*) FROM dune.player_state'))!=expected:raise ValueError('The player count changed during the official migration; recovery is required.')

    def prepare_generation(self,template,plan):
        self.phase('preparing-components')
        credentials=self.m.read_credentials(self.s)
        specs={name:queue_spec(name,plan,template,credentials['tls']) for name in ('rmq-admin','rmq-game')}
        specs.update(service_specs(plan,template,credentials))
        source=self.run['previous']['directorIni']
        ini=native_director_ini(source,plan,self.s.get('manualPins'))
        specs['director']['files']['Tools/Battlegroups/Director/BattlegroupDirector/director_config.ini']['data']=ini
        bridge=self.e.request('GET','/networks/'+plan['network'])['IPAM']['Config'][0]['Gateway']
        parts={int(name[5:]) for name in self.run['previous']['services'] if name.startswith('game-')}
        parts.update(p for row in plan['maps'] for p in row['partitions'][:row['initialReplicas']])
        for partition in sorted(parts):
            spec=game_spec(plan,partition,credentials,bridge,{})
            for volume in spec['volumes']:volume['mustBeNew']=False
            specs['game-'+str(partition)]=spec
        self.s['worldPlan']=plan;self.s['directorIni']=ini
        self.s['classicAutomaticMaps']=classic_automatic_maps(template['world']['spec']['utilities']['director']['spec']['configFiles']['files']['director.ini'])
        def persist(value):
            if value.get('generationChange'):value['updateRun']['generationId']=value['generationChange']['id']
            self.m.save(value)
        service_generations.replace_generation(self.s,self.e,specs,plan,persist,'update',previous_plan=self.run['previous']['worldPlan'],previous_profile=self.run['previous']['profile'])
        self.s['connections']['rmq-game']['tlsSha256']=hashlib.sha256(credentials['tls']['ca.pem']+credentials['tls']['cert.pem']).hexdigest();self.m.save(self.s)

    def ready(self,published):
        while True:
            try:status=self.m.public_state(self.s,self.e)
            except (OSError,EngineError):time.sleep(2);continue
            selected=[r for r in status['services'] if r['component'].startswith('game-') and r['desiredState']=='running']
            if any(r['state'] in {'exited','dead'} for r in selected):raise ValueError('A selected map exited before update readiness.')
            if not self.run.get('playersObserved') and any(r.get('players',0)>0 for r in selected if r.get('players') is not None):self.phase(self.run['phase'],playersObserved=True)
            core=[r for r in status['services'] if r['component'] in (('director','text-router','gateway') if published else ('director','text-router'))]
            if len(core)!=(3 if published else 2) or any(r['state'] in {'exited','dead'} for r in core):raise ValueError('A required core component is missing or exited during update readiness.')
            queues=status.get('connectionServices',[])
            if status.get('database',{}).get('health')=='unhealthy' or any(r.get('health')=='unhealthy' for r in queues):raise ValueError('A required database or queue became unhealthy during update readiness.')
            if all(r.get('gameReady') is True for r in selected) and all(r['state']=='running' for r in core) and len(queues)==2 and all(r.get('health')=='healthy' for r in queues) and status.get('database',{}).get('health')=='healthy':return
            # Alive-but-unready processes remain an active, observable operation.
            # No restart/rollback is inferred from an observation timeout.
            time.sleep(3)

    def apply(self,build,allow_online=False):
        if not isinstance(build,str) or not re.fullmatch(r'[0-9]{1,18}',build) or type(allow_online) is not bool:raise ValueError('Invalid update request.')
        if (self.s.get('regisSupport') or {}).get('enabled') or self.s.get('pendingRegisChange'):
            raise ValueError('Disable Tank compatibility in Server Settings before a normal server update. Saved Tanks require compatibility; nothing was stopped or updated.')
        previous_run=self.s.get('updateRun')
        if previous_run and previous_run['phase'] not in TERMINAL:raise ValueError('Recover the previous update before starting another.')
        if self.s['phase']!='database-ready' or self.s.get('generationChange') or self.s.get('pendingAddressChange'):raise ValueError('Finish the current database or configuration operation before updating.')
        if any(e['phase'] in {'preparing','running'} or e.get('verification',{}).get('phase') in {'preparing','running'} for e in self.s.get('backups',{}).values()):raise ValueError('Wait for the active backup operation before updating.')
        if (self.s.get('assetUpdate') or {}).get('phase') in {'applied','rolled-back','failed'}:
            self.s.setdefault('assetUpdateHistory',[]).append(self.s.pop('assetUpdate'))
        self.s['updateRun']={'id':self.s['operation']['id'],'phase':'staging','build':build,'startedAt':time.time()};self.m.save(self.s)
        try:
            if not self.s.get('assetUpdate'):asset_updates.start_stage(self.s,self.e,build,self.m.save)
            while True:
                update,changed=asset_updates.observe_stage(self.s,self.e)
                if changed:self.m.save(self.s)
                if update['expectedBuild']!=build:raise ValueError('The staged package is for a different build.')
                if update['phase']=='ready':break
                if update['phase']=='failed':raise ValueError('The official package could not be staged.')
                if update['phase'] not in {'preparing','downloading'}:raise ValueError('Recover the previous package operation before updating.')
                time.sleep(1)
            self.phase('validating',stageId=update['id'])
            root=Path('/assets/staged')/update['id'];template=read_template(root/'server/scripts/setup/templates/world-template.yaml')
            report=json.loads((root/'install-state.json').read_text())
            plan=plan_world(self.s['id'],self.s['profile'],template,report,self.s['database'],self.s.get('mapMemoryOverrides'))
            if any(int(name[5:]) not in {r['partition'] for r in plan['games']} for name in self.s['services'] if name.startswith('game-')):raise ValueError('An installed map was removed from this package; review its saved data before updating.')
            status=self.m.public_state(self.s,self.e)
            if not allow_online and any(r.get('players')!=0 for r in status['services'] if r['component'].startswith('game-') and r['state']=='running'):raise ValueError('Players connected or occupancy became unknown while staging. Review the update again.')
            keys=('worldPlan','profile','services','connections','mapTargets','manualPins','classicAutomaticMaps','partitionPlan')
            previous={key:copy.deepcopy(self.s[key]) for key in keys if key in self.s}
            previous['desiredState']=self.s.get('desiredState','stopped')
            previous['directorIni']=self.e.read_director_config(self.s['services']['director']['id'],self.s['id']).decode('utf-8')
            self.phase('stopping',previous=previous,stopStarted=True);self.maintenance(True);self.m.stop_services(self.s,self.e)
            self.backup();self.phase('activating-package');self.s['assetUpdate']['phase']='activating';self.m.save(self.s);self.switch('activate')
            self.migrate()
            self.phase('checking-partitions');self.sql(partition_upgrade_sql(template['partitions']))
            self.s['partitionPlan']={'sha256':template['sha256'],'rows':template['partitions']};self.m.save(self.s)
            self.prepare_generation(template,plan)
            if previous['desiredState']=='running':
                self.phase('checking-maps');self.m.start_services(self.s,self.e,publish_gateway=False);self.ready(False)
            self.phase('committing');service_generations.commit_generation(self.s,self.m.save)
            self.phase('publishing',committed=True)
            if previous['desiredState']=='running':self.m.start_services(self.s,self.e);self.ready(True)
            self.s['assetUpdate']['phase']='applied';self.maintenance(False);self.phase('completed',finishedAt=time.time())
            return {'updated':True,'build':build,'running':previous['desiredState']=='running'}
        except Exception as error:
            self.run['error']=str(error);self.m.save(self.s)
            if not self.run.get('stopStarted'):self.phase('failed-preflight');raise
            if self.run.get('committed') or self.run.get('playersObserved'):
                self.phase('recovery-required');raise ValueError('The new version needs recovery review; no stale database backup was restored over possible new player progress.') from error
            try:self.recover()
            except Exception as recovery:
                self.phase('recovery-required',recoveryError=str(recovery));raise ValueError('Update recovery needs review. The backup and previous resources were retained.') from recovery
            raise ValueError('The update failed and the previous version was restored: '+str(error)) from error

    def recover(self):
        if self.run['phase'] in TERMINAL:raise ValueError('There is no interrupted update to recover.')
        if not self.run.get('stopStarted'):self.phase('failed-preflight');return
        if self.run.get('committed'):
            self.maintenance(True)
            self.demote()
            if self.run['previous']['desiredState']=='running':self.m.start_services(self.s,self.e);self.ready(True)
            self.s['assetUpdate']['phase']='applied';self.maintenance(False);self.phase('completed',finishedAt=time.time());return
        if self.run.get('playersObserved'):raise ValueError('Review player progress before restoring the pre-update database.')
        self.phase('recovering')
        self.maintenance(True)
        for key,component in (('activateJob','asset-switch'),('migrationJob','db-migrate')):
            if self.run.get(key):
                observed=self.owned_job(self.run[key],component)
                if observed['State']['Status'] not in {'created','exited','dead'}:self.wait_job(self.run[key],component,success=False)
        self.m.stop_services(self.s,self.e);self.demote()
        if not self.s.get('generationChange') and self.run.get('generationId'):
            old=next((r for r in reversed(self.s.get('generationHistory',[])) if r['id']==self.run['generationId']),None)
            if old and old['phase']=='committed':self.s['generationChange']=copy.deepcopy(old)
        if self.s.get('generationChange'):service_generations.rollback_generation(self.s,self.e,self.m.save)
        journal=Path('/assets/staged')/self.run['stageId']/'activation-state.json'
        if journal.exists():self.switch('rollback')
        previous=self.run['previous']
        for key,value in previous.items():
            if key!='desiredState':self.s[key]=copy.deepcopy(value)
        self.s['desiredState']='stopped';self.m.save(self.s)
        if self.run.get('schemaMayHaveChanged'):
            if self.s.get('restore',{}).get('keepMaintenance') and self.s['restore']['phase'] in {'restoring','recovering','recovery-required'}:
                self.m.finish_restore(self.s,self.e)
            else:self.m.restore_backup(self.s,self.e,self.run['backupId'],'RESTORE',keep_maintenance=True)
        if previous['desiredState']=='running':self.m.start_services(self.s,self.e,publish_gateway=False);self.ready(False);self.m.start_services(self.s,self.e);self.ready(True)
        self.maintenance(False);self.s['assetUpdate']['phase']='rolled-back';self.phase('rolled-back',finishedAt=time.time())
