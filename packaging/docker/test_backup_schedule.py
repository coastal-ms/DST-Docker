from datetime import datetime,timezone
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import backup_schedule as policy
import backup_storage
import manager


def at(value):return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()


class PolicyTests(unittest.TestCase):
    def test_presets_use_the_latest_utc_slot_without_drift(self):
        now=at('2026-11-09T17:12:00')
        for preset,expected in [('Hourly','2026-11-09T17:00:00'),('Every6Hours','2026-11-09T12:00:00'),
                                 ('DailyUtc04','2026-11-09T04:00:00'),('TwiceDailyUtc','2026-11-09T16:00:00'),
                                 ('WeeklyMonUtc04','2026-11-09T04:00:00')]:
            self.assertEqual(policy.slot(preset,now),at(expected))
        self.assertEqual(policy.slot('WeeklyMonUtc04',at('2026-11-09T03:00:00')),at('2026-11-02T04:00:00'))
        self.assertEqual(policy.slot('TwiceDailyUtc',at('2026-11-09T03:00:00')),at('2026-11-08T16:00:00'))

    def test_configuration_does_not_backfill_and_clock_rollback_does_not_duplicate(self):
        state={};policy.configure(state,{'preset':'Hourly'},at('2026-11-09T08:15:00'))
        self.assertIsNone(policy.due(state,at('2026-11-09T08:16:00')))
        self.assertEqual(policy.due(state,at('2026-11-09T09:01:00')),at('2026-11-09T09:00:00'))
        state['scheduledBackup']={'slot':at('2026-11-09T09:00:00'),'phase':'completed'}
        self.assertIsNone(policy.due(state,at('2026-11-09T09:05:00')))
        self.assertIsNone(policy.due(state,at('2026-11-09T08:20:00')))
        self.assertIsNone(policy.due(state,at('2026-11-09T10:40:00')))

    def test_schedule_and_retention_refuse_coercion_and_unbounded_values(self):
        for request in ({'preset':'Unknown'},{'preset':True},{'keepLast':True},{'keepLast':'8'},
                        {'keepLast':1001},{'keepLastPods':101},{'keepDaysPods':-1}):
            state={}
            with self.assertRaises(ValueError):policy.configure(state,request,1)
            self.assertNotIn('backupSchedule',state)

    def test_retention_protects_newest_recovery_and_active_verification(self):
        state={'backups':{str(index):{'phase':'completed','createdAt':index,'sha256':'a'*64} for index in range(5)},
               'restore':{'backupId':'0'},'updateRun':{'backupId':'1'}}
        state['backups']['2']['verification']={'phase':'running'}
        self.assertEqual(policy.retained_ids(state,1),['3'])
        self.assertEqual(policy.retained_ids(state,0),[])


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.name='backup-12345678-abcdef12.dump';(self.root/self.name).write_bytes(b'original-owned-backup')
        self.row={'name':self.name,'sha256':hashlib.sha256(b'original-owned-backup').hexdigest()}
    def tearDown(self):self.temp.cleanup()

    def test_exact_backup_deletion_is_idempotent_and_keeps_other_files(self):
        (self.root/'important.txt').write_text('keep')
        self.assertEqual(backup_storage.remove(self.root,[self.row]),[self.name])
        self.assertEqual(backup_storage.remove(self.root,[self.row]),[self.name])
        self.assertEqual((self.root/'important.txt').read_text(),'keep')

    def test_bad_name_or_checksum_prevents_any_batch_deletion(self):
        for row in ({'name':'../important.dump','sha256':'a'*64},{**self.row,'sha256':'b'*64}):
            with self.assertRaises(ValueError):backup_storage.remove(self.root,[self.row,row])
            self.assertTrue((self.root/self.name).exists())

    def test_linked_backup_is_rejected_without_touching_external_target(self):
        other=self.root/'outside';other.write_bytes(b'original-owned-backup')
        (self.root/self.name).unlink();os.link(other,self.root/self.name)
        with self.assertRaises(ValueError):backup_storage.remove(self.root,[self.row])
        self.assertEqual(other.read_bytes(),b'original-owned-backup')
        (self.root/self.name).unlink();(self.root/self.name).symlink_to(other)
        with self.assertRaises(OSError):backup_storage.remove(self.root,[self.row])
        self.assertEqual(other.read_bytes(),b'original-owned-backup')

    def test_browser_export_is_exact_and_publishes_only_after_hash_verification(self):
        output=self.root/'exports';output.mkdir()
        request={**self.row,'id':'a'*32,'bytes':len(b'original-owned-backup')}
        result=backup_storage.export(self.root,output,request)
        self.assertEqual(result['sha256'],self.row['sha256'])
        self.assertEqual((output/('a'*32+'.backup')).read_bytes(),b'original-owned-backup')
        self.assertEqual((output/('a'*32+'.backup')).stat().st_mode&0o777,0o644)
        self.assertEqual((self.root/self.name).read_bytes(),b'original-owned-backup')
        with self.assertRaises(ValueError):backup_storage.export(self.root,output,{**request,'id':'b'*32,'sha256':'c'*64})
        self.assertFalse((output/('b'*32+'.backup')).exists())
        self.assertFalse((output/('b'*32+'.partial')).exists())


class WorkerTests(unittest.TestCase):
    def test_cleanup_commit_requires_matching_success_report_and_retains_failed_intent(self):
        state={'id':'a'*32,'backups':{'backup':{'phase':'completed'}},'backupCleanup':{
            'ids':['backup'],'files':[{'name':'backup-12345678-abcdef12.dump','sha256':'b'*64}],'job':'owned-job','phase':'running'}}
        engine=Mock(spec=manager.Engine);engine.assert_owned.return_value={'State':{'Status':'exited','ExitCode':0}}
        engine.backup_report.return_value={'ok':True,'deleted':['other-file']}
        with patch.object(manager,'save'):
            manager.observe_backup_cleanup(state,engine)
            self.assertEqual(state['backups']['backup']['phase'],'completed')
            self.assertEqual(state['backupCleanup']['phase'],'failed')
            engine.backup_report.return_value={'ok':True,'deleted':['backup-12345678-abcdef12.dump']}
            manager.observe_backup_cleanup(state,engine)
        self.assertEqual(state['backups']['backup']['phase'],'deleted');self.assertNotIn('backupCleanup',state)

    def test_job_cleanup_never_removes_active_helpers_or_the_current_recovery_job(self):
        state={'id':'a'*32,'restore':{'job':'protected'},'backups':{}}
        engine=Mock(spec=manager.Engine)
        engine.backup_jobs.return_value=[{'id':key,'createdAt':stamp,'state':status,'component':'db-backup'}
            for key,stamp,status in [('running',4,'running'),('new',3,'exited'),('protected',2,'exited'),('old',1,'exited')]]
        with patch.object(manager,'save'):
            result=manager.prune_backup_jobs(state,engine,1,0)
        self.assertEqual([row['id'] for row in result['deleted']],['old'])
        engine.remove_backup_job.assert_called_once_with('a'*32,engine.backup_jobs.return_value[-1])

    def state(self):
        value={'id':'a'*32,'phase':'database-ready','database':{'id':'owned-db'},'backups':{}}
        policy.configure(value,{'preset':'Hourly','keepLast':8},at('2026-11-09T08:00:01'))
        return value

    def test_scheduled_and_manual_backups_use_the_same_creation_job_and_filename(self):
        now = at('2026-11-09T09:01:00')
        args_by_source = []
        for scheduled in (False, True):
            state = self.state()
            state['worldId'] = 'sh-coastal-abcdef'
            state['database']['network'] = 'owned-network'
            engine = Mock(spec=manager.Engine)
            engine.assert_owned.side_effect = lambda _, __, component: {
                'State': {'Status': 'running', 'Health': {'Status': 'healthy'}}
                if component == 'postgres' else {'Status': 'created'}}
            engine.inspect.return_value = {'Mounts': [{'Destination': '/projects', 'Type': 'volume', 'Name': 'project-state'}]}
            engine.create_backup_job.return_value = 'owned-job'
            assets = {'images': [{'archive': 'battlegroup/server-db-utils.tar', 'tags': ['fixture']}]}
            with (patch.dict(manager.os.environ, {'HOSTNAME': 'manager'}),
                  patch.object(manager, 'project_state', return_value=state), patch.object(manager, 'save'),
                  patch.object(manager, 'assets_state', return_value=assets), patch.object(manager, 'public_state'),
                  patch.object(manager.Path, 'read_text', return_value='backup helper'),
                  patch.object(manager.time, 'time', return_value=now)):
                if scheduled:
                    manager.backup_schedule_tick(engine, now)
                else:
                    manager.start_backup(state, engine)
            entry, = state['backups'].values()
            self.assertEqual(entry['name'], 'sh-coastal-abcdef-20261109-090100.backup')
            self.assertEqual('scheduledSlot' in entry, scheduled)
            args_by_source.append(engine.create_backup_job.call_args.args)
            engine.lifecycle.assert_called_once_with('owned-job', state['id'], 'start')
        self.assertEqual(*args_by_source)

    def test_restore_safety_backup_uses_the_same_filename_format(self):
        state = self.state()
        state['worldId'] = 'sh-coastal-abcdef'
        state['database']['network'] = 'owned-network'
        backup_id = 'b' * 32
        state['backups'][backup_id] = {
            'phase': 'completed', 'name': 'backup-123-abcdef12.dump', 'sha256': 'a' * 64,
            'verification': {'phase': 'completed', 'restored': dict.fromkeys(
                ('duneTables', 'duneViews', 'partitions', 'players'), 1)},
        }
        engine = Mock(spec=manager.Engine)
        engine.inspect.return_value = {'Mounts': [{'Destination': '/projects', 'Type': 'volume', 'Name': 'project-state'}]}
        assets = {'images': [{'archive': 'battlegroup/server-db-utils.tar', 'tags': ['fixture']}]}
        with (patch.dict(manager.os.environ, {'HOSTNAME': 'manager'}), patch.object(manager, 'save'),
              patch.object(manager, 'assets_state', return_value=assets), patch.object(manager, 'atomic'),
              patch.object(manager, 'stop_services'), patch.object(manager, 'finish_restore'),
              patch.object(manager.Path, 'read_text', return_value='restore helper'),
              patch.object(manager.time, 'time', return_value=at('2026-11-09T09:01:00'))):
            manager.restore_backup(state, engine, backup_id, 'RESTORE')
        name = 'sh-coastal-abcdef-20261109-090100.backup'
        self.assertEqual(state['restore']['beforeName'], name)
        self.assertEqual(engine.create_restore_job.call_args.args[-2], name)

    def test_stopped_database_does_not_start_any_container_or_consume_the_slot(self):
        state=self.state();engine=Mock(spec=manager.Engine)
        engine.assert_owned.return_value={'State':{'Status':'exited','Health':{'Status':'healthy'}}}
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'save') as save,patch.object(manager,'start_backup') as start:
            manager.backup_schedule_tick(engine,at('2026-11-09T09:01:00'))
            start.assert_not_called();save.assert_not_called();engine.lifecycle.assert_not_called()
            self.assertNotIn('scheduledBackup',state)

    def test_active_maintenance_and_pending_changes_defer_before_dispatch(self):
        for change in ({'operation':{'phase':'running'}},{'restore':{'phase':'recovery-required'}},
                       {'pendingResourceChange':{'id':'pending'}},{'backups':{'pending':{'phase':'running','job':'job'}}}):
            state={**self.state(),**change};engine=Mock(spec=manager.Engine)
            engine.assert_owned.return_value={'State':{'Status':'running','Health':{'Status':'healthy'}}}
            with patch.object(manager,'project_state',return_value=state),patch.object(manager,'save'),patch.object(manager,'start_backup') as start:
                manager.backup_schedule_tick(engine,at('2026-11-09T09:01:00'))
                start.assert_not_called()

    def test_unidentified_interrupted_dispatch_is_visible_and_never_duplicated(self):
        state=self.state();state['scheduledBackup']={'phase':'dispatching','slot':at('2026-11-09T09:00:00')}
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'save'),patch.object(manager,'start_backup') as start:
            manager.backup_schedule_tick(Mock(),at('2026-11-09T09:02:00'))
            self.assertEqual(state['scheduledBackup']['phase'],'review-required');start.assert_not_called()

    def test_successful_run_is_journaled_before_dispatch(self):
        state=self.state();engine=Mock(spec=manager.Engine)
        engine.assert_owned.return_value={'State':{'Status':'running','Health':{'Status':'healthy'}}}
        events=[]
        def save(value):events.append(('save',value.get('scheduledBackup',{}).get('phase')))
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'save',side_effect=save),patch.object(manager,'start_backup',side_effect=lambda *_:events.append(('start',None))):
            manager.backup_schedule_tick(engine,at('2026-11-09T09:01:00'))
        self.assertEqual(events,[('save','dispatching'),('start',None)])
        self.assertRegex(state['scheduledBackup']['requestId'],r'^[a-f0-9]{32}$')

class ImportManagerTests(unittest.TestCase):
    def test_import_is_explicit_and_resumes_one_identity_without_starting_database(self):
        state={'id':'a'*32,'backups':{}}
        request={'trustedSource':True,'uploadId':'b'*32,'sha256':'c'*64,'bytes':512}
        engine=Mock(spec=manager.Engine);engine.create_backup_import_job.return_value='job'
        engine.assert_owned.return_value={'State':{'Status':'created'}}
        assets={'images':[{'archive':'battlegroup/server-db-utils.tar','tags':['registry.funcom.com/funcom/self-hosting/seabass-server-db-utils:fixture']}]}
        with patch.object(manager,'save'),patch.object(manager,'assets_state',return_value=assets),patch.object(manager.Path,'read_text',return_value='trusted job source'):
            with self.assertRaises(ValueError):manager.start_backup_import(state,engine,{**request,'trustedSource':False})
            self.assertFalse(state['backups'])
            manager.start_backup_import(state,engine,request)
            name=state['backups'][request['uploadId']]['name']
            engine.assert_owned.return_value={'State':{'Status':'running'}}
            manager.start_backup_import(state,engine,request)
        self.assertEqual(len(state['backups']),1)
        self.assertEqual(state['backups'][request['uploadId']]['name'],name)
        self.assertEqual(engine.create_backup_import_job.call_args_list[0],engine.create_backup_import_job.call_args_list[1])
        engine.lifecycle.assert_called_once_with('job','a'*32,'start')
        engine.exec_internal.assert_not_called()

    def test_import_report_must_match_the_staged_source_before_becoming_completed(self):
        entry={'phase':'running','source':'import','uploadId':'b'*32,'name':'backup-1-abcdef12.dump','sha256':'c'*64,'bytes':512,'job':'job'}
        state={'id':'a'*32,'backups':{'b'*32:entry}}
        engine=Mock(spec=manager.Engine);engine.assert_owned.return_value={'State':{'Status':'exited','ExitCode':0}}
        report={'ok':True,'mode':'import','uploadId':'b'*32,'name':entry['name'],'sha256':'d'*64,'bytes':512}
        with patch.object(manager,'save'),patch.object(manager,'finished_backup_report',return_value=report):manager.observe_backup_jobs(state,engine)
        self.assertEqual(entry['phase'],'failed')
        self.assertNotIn('verification',entry)

class DatabaseOnlyControlTests(unittest.TestCase):
    def test_stop_refuses_running_world_or_active_backup_without_lifecycle_changes(self):
        engine=Mock(spec=manager.Engine)
        state={'id':'a'*32,'phase':'database-ready','desiredState':'running','database':{'id':'database'},'services':{},'backups':{}}
        with self.assertRaises(ValueError):manager.stop_database_only(state,engine)
        state['desiredState']='stopped';state['backups']={'one':{'phase':'running'}}
        with self.assertRaises(ValueError):manager.stop_database_only(state,engine)
        engine.lifecycle.assert_not_called()

class DeletedImportTests(unittest.TestCase):
    def test_deleted_import_is_not_republished_from_an_old_completed_job(self):
        upload='b'*32
        entry={'source':'import','uploadId':upload,'sha256':'c'*64,'bytes':512,'phase':'deleted'}
        state={'id':'a'*32,'backups':{upload:entry}}
        engine=Mock(spec=manager.Engine)
        with self.assertRaisesRegex(ValueError,'deleted'):
            manager.start_backup_import(state,engine,{'uploadId':upload,'sha256':'c'*64,'bytes':512,'trustedSource':True})
        engine.create_backup_import_job.assert_not_called()
