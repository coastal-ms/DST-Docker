import copy,json,tempfile,time,types,unittest
from pathlib import Path
from unittest.mock import patch
import world_restart,world_research,backup_schedule

class RestartTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data={'original':True};self.maintenance=False;self.fault='';self.restores=[];self.started=False
        self.state={'id':'a'*32,'worldId':'world-fixture','phase':'database-ready','worldPlan':{'prepared':True},'desiredState':'stopped',
                    'services':{'game-1':{'id':'game'}},'operation':{'id':'b'*32,'phase':'running'},'backups':{}}
        def status(*args):return {'database':{'state':'running','health':'healthy'},'services':[{'component':'game-1','state':'running' if self.started else 'exited','players':0,'heartbeatAt':time.time()}]}
        def stop(state,engine):self.started=False;state['desiredState']='stopped'
        def start(state,engine,publish_gateway=True):
            self.started=True;state['desiredState']='running'
            if self.fault=='publish':self.data['new-progress']=True;self.fault='';raise ValueError('Interrupted publication')
        def restore(state,engine,key,*args,**kwargs):
            self.assertTrue(self.maintenance);self.assertFalse(self.started);self.restores.append(key)
            self.data=copy.deepcopy(self.saved if key=='original-backup' else {})
            state['restore']={'phase':'completed'}
            if self.fault=='after-promotion':self.fault='';raise ValueError('Interrupted postflight')
        self.host=types.SimpleNamespace(CONFIG=Path(self.temp.name),save=lambda state:None,public_state=status,stop_services=stop,start_services=start,restore_backup=restore)
        self.host.atomic=lambda path,data,*args:setattr(self,'maintenance',json.loads(data)['active'])
        self.engine=types.SimpleNamespace(assert_owned=lambda *args:{'State':{'Status':'running' if self.started else 'exited'}})
        outer=self
        class Controller(world_restart.NativeWorldRestart):
            def backup(inner):
                if outer.fault=='backup':raise ValueError('Backup failed')
                outer.saved=copy.deepcopy(outer.data);inner.run['backupId']='original-backup'
                inner.s['backups']['original-backup']={'name':'backup-1-abcdef12.dump','phase':'completed','createdAt':1}
            def fresh_archive(inner):
                inner.run['freshBackupId']='fresh';inner.s['backups']['fresh']={'name':'backup-2-abcdef12.dump','phase':'completed','createdAt':2}
                if outer.fault=='fresh':raise ValueError('Fresh schema failed')
            def gameplay_count(inner):return int('new-progress' in outer.data)
            def ready(inner,published):pass
        self.control=Controller(self.state,self.engine,self.host)
        self.patch=patch.object(world_restart,'read_template',return_value={'sha256':'c'*64});self.patch.start();self.addCleanup(self.patch.stop)
        self.capture=patch.object(world_research,'capture',return_value={'characters':[],'pairCount':0});self.capture.start();self.addCleanup(self.capture.stop)

    def test_success_preserves_stopped_state_and_explicit_rollback(self):
        self.control.apply('RESTART WORLD');self.assertEqual(self.data,{})
        self.assertEqual(self.state['worldRestart']['phase'],'done');self.assertFalse(self.started);self.assertFalse(self.maintenance)
        self.control.rollback('ROLL BACK WORLD');self.assertEqual(self.data,{'original':True});self.assertEqual(self.state['worldRestart']['phase'],'rolled-back')

    def test_bad_confirmation_and_unknown_running_occupancy_cannot_start_mutation(self):
        with self.assertRaises(ValueError):self.control.apply('restart world')
        self.assertNotIn('worldRestart',self.state);self.assertFalse(self.maintenance)
        self.host.public_state=lambda *args:{'services':[{'component':'game-1','state':'running','players':None}]}
        with self.assertRaises(ValueError):self.control.assert_offline()
        self.assertFalse(self.maintenance)

    def test_backup_or_fresh_failure_preserves_original_without_restore(self):
        for fault in ('backup','fresh'):
            with self.subTest(fault=fault):
                self.fault=fault
                with self.assertRaises(ValueError):self.control.apply('RESTART WORLD')
                self.assertEqual(self.data,{'original':True});self.assertEqual(self.restores,[])
                self.assertEqual(self.state['worldRestart']['phase'],'failed-preflight');self.assertFalse(self.maintenance)

    def test_interruption_after_promotion_restores_exact_backup_before_access(self):
        self.fault='after-promotion'
        with self.assertRaises(ValueError):self.control.apply('RESTART WORLD')
        self.assertEqual(self.data,{'original':True});self.assertEqual(self.restores,['fresh','original-backup'])
        self.assertEqual(self.state['worldRestart']['phase'],'rolled-back');self.assertFalse(self.maintenance)

    def test_publication_failure_never_rolls_back_new_progress(self):
        self.state['desiredState']='running';self.fault='publish'
        self.control.apply('RESTART WORLD')
        self.assertTrue(self.data['new-progress']);self.assertEqual(self.restores,['fresh'])
        self.assertTrue(self.state['worldRestart']['committed']);self.assertEqual(self.state['worldRestart']['phase'],'done')

    def test_explicit_rollback_blocks_after_new_gameplay_records(self):
        self.control.apply('RESTART WORLD');self.data['new-progress']=True
        with self.assertRaisesRegex(ValueError,'new gameplay'):self.control.rollback('ROLL BACK WORLD')
        self.assertTrue(self.data['new-progress']);self.assertEqual(self.restores,['fresh'])

    def test_recovery_archives_survive_retention(self):
        self.control.apply('RESTART WORLD')
        self.state['backups']['latest']={'name':'backup-3-abcdef12.dump','phase':'completed','createdAt':3}
        self.assertEqual(backup_schedule.retained_ids(self.state,1),[])

class ResearchTests(unittest.TestCase):
    def fixture(self):return {'characterName':'Fixture','accountId':1,'funcomId':'fixture-id','pawnId':2,'online':'Offline','researchHash':'a'*64,
                              'research':[{'ItemKey':'RCP_Recipe','UnlockedState':'Purchased','unrelated':{'keep':1}}],
                              'runtime':[{'BaseRecipeId':{'Name':'Recipe'}}]}
    def test_capture_requires_proven_runtime_and_audit_matches_exact_identity(self):
        row=self.fixture();query=lambda _:json.dumps([row]);snapshot=world_research.capture(query)
        self.assertEqual(snapshot['pairCount'],1);row['runtime']=[]
        audit=world_research.audit(query,snapshot);self.assertEqual(len(audit['mismatches']),1)
        row['funcomId']='other';self.assertEqual(world_research.audit(query,snapshot)['pendingCharacters'],['Fixture'])
    def test_recovery_preserves_other_json_and_rejects_unknown_items_or_online_player(self):
        row=self.fixture();query=lambda _:json.dumps([row]);snapshot=world_research.capture(query);row['runtime']=[]
        statement,updated,keys=world_research.recovery_sql(query,snapshot,'Fixture','fixture-id',['RCP_Recipe'])
        self.assertEqual(updated,[row['research'][0]|{'UnlockedState':'NotPurchased'}]);self.assertIn("ps.online_status::text='Offline'",statement)
        self.assertIn('RETURNING a.id',statement);self.assertEqual(keys,{'RCP_Recipe'})
        with self.assertRaises(ValueError):world_research.recovery_sql(query,snapshot,'Fixture','fixture-id',['RCP_Other'])
        row['online']='Online'
        with self.assertRaises(ValueError):world_research.recovery_sql(query,snapshot,'Fixture','fixture-id',['RCP_Recipe'])

class ResearchRecoveryTransactionTests(unittest.TestCase):
    setUp=RestartTransactionTests.setUp
    def test_research_verification_failure_restores_dedicated_backup_before_access(self):
        self.state['worldRestart']={'phase':'done','researchSnapshot':{'characters':[{'pairs':[]} ]}}
        outer=self
        class Recovery(world_research.NativeResearchRecovery):
            def backup(inner):
                outer.saved=copy.deepcopy(outer.data);inner.run['backupId']='original-backup'
                inner.s['backups']['original-backup']={'name':'backup-1-abcdef12.dump','phase':'completed','createdAt':1}
            def sql(inner,query):
                if query=='typed-research-write':outer.data={'partially-written':True};return '1'
                raise AssertionError('Unexpected SQL')
            def ready(inner,published):pass
        control=Recovery(self.state,self.engine,self.host)
        with patch.object(world_research,'recovery_sql',return_value=('typed-research-write',[],{'RCP_Fixture'})),patch.object(world_research,'verify',side_effect=ValueError('Readback mismatch')):
            with self.assertRaisesRegex(ValueError,'Readback mismatch'):control.apply_research('RESET RESEARCH','Fixture','fixture',['RCP_Fixture'])
        self.assertEqual(self.restores,['original-backup']);self.assertEqual(self.data,{'original':True})
        self.assertEqual(self.state['worldResearchRecovery']['phase'],'rolled-back');self.assertFalse(self.started);self.assertFalse(self.maintenance)

    def test_research_recovery_never_accepts_wrong_confirmation(self):
        control=world_research.NativeResearchRecovery(self.state,self.engine,self.host)
        with self.assertRaises(ValueError):control.apply_research('wrong','Fixture','fixture',['RCP_Fixture'])
        self.assertNotIn('worldResearchRecovery',self.state);self.assertFalse(self.maintenance)

if __name__=='__main__':unittest.main()
