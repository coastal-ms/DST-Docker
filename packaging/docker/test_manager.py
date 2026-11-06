import json
from pathlib import Path
import sys
import tempfile
import unittest
import threading
import time
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).parent))
import manager


class FakeEngine:
    def __init__(self): self.creates=0; self.execs=[]; self.health='healthy'
    def ensure_package_image(self,*args): pass
    def create_database(self,*args): self.creates+=1; raise RuntimeError('ambiguous engine outcome')
    def assert_owned(self,*args): return {'State':{'Status':'running','Health':{'Status':self.health}}}
    def exec_internal(self,*args): self.execs.append(args); return ''


class ManagerTests(unittest.TestCase):
    def test_journal_write_is_synced_before_replacing_the_previous_record(self):
        target=self.root/'journal.json';target.write_text('previous')
        with patch.object(manager.os,'fsync',side_effect=OSError('qualification sync failure')):
            with self.assertRaisesRegex(OSError,'sync failure'):manager.atomic(target,'candidate')
        self.assertEqual(target.read_text(),'previous')
        manager.atomic(target,'candidate')
        self.assertEqual(target.read_text(),'candidate')

    def test_active_operation_status_does_not_persist_a_stale_copy_when_staging_finishes(self):
        state={'id':'a'*32,'phase':'new','operation':{'id':'owned','phase':'running'}}
        with patch.object(manager.asset_updates,'observe_stage',return_value=({'phase':'ready'},True)),patch.object(manager,'save') as save:
            manager.public_state(state,FakeEngine())
        save.assert_not_called()

    def test_update_restore_keeps_the_management_maintenance_guard_until_its_parent_finishes(self):
        state=manager.project_state();state['restore']={'id':'a'*32,'name':'backup-fixture.dump','job':'owned','resume':False,'keepMaintenance':True}
        config=self.root/'config';config.mkdir();(config/'docker-maintenance.json').write_text('{"active":true}')
        engine=Mock(spec=manager.Engine);engine.assert_owned.return_value={'State':{'Status':'exited','ExitCode':0}}
        engine.backup_report.return_value={'operationId':'a'*32,'target':'dune','name':'backup-fixture.dump','phase':'completed','ok':True}
        with patch.object(manager,'CONFIG',config),patch.object(manager,'public_state',return_value={}):manager.finish_restore(state,engine)
        self.assertTrue(json.loads((config/'docker-maintenance.json').read_text())['active'])
        self.assertEqual(state['restore']['phase'],'completed')

    def test_unpublished_start_refuses_a_running_gateway_without_stopping_it(self):
        state={'id':'a'*32,'services':{'gateway':{'id':'owned'}}};engine=Mock(spec=manager.Engine)
        engine.assert_owned.return_value={'State':{'Status':'running'}}
        with self.assertRaisesRegex(ValueError,'Stop the gateway'):manager.start_services(state,engine,publish_gateway=False)
        engine.lifecycle.assert_not_called()

    def test_gateway_publication_flag_is_only_accepted_as_a_boolean_for_start(self):
        for action,value in [('services.start','false'),('services.stop',False)]:
            state={'id':'a'*32}
            with patch.object(manager,'project_state',return_value=state),patch.object(manager,'save') as save:
                with self.assertRaisesRegex(ValueError,'typed start'):manager.dispatch({'action':action,'publishGateway':value},FakeEngine())
                save.assert_not_called();self.assertNotIn('operation',state)

    def test_backup_completion_can_be_observed_without_releasing_the_owning_update_operation(self):
        state={'id':'a'*32,'operation':{'id':'update','phase':'running'},'backups':{'backup':{'phase':'running','job':'owned','name':'backup-fixture.dump'}}}
        engine=Mock(spec=manager.Engine)
        engine.assert_owned.return_value={'State':{'Status':'exited','ExitCode':0}}
        engine.backup_report.return_value={'ok':True,'name':'backup-fixture.dump','mode':'create','sha256':'b'*64,'bytes':100}
        with patch.object(manager,'save'):manager.observe_backup_jobs(state,engine)
        self.assertEqual(state['backups']['backup']['phase'],'completed')
        self.assertEqual(state['operation'],{'id':'update','phase':'running'})

    def test_map_memory_increase_is_applied_and_persisted_for_future_preparation(self):
        state={'id':'a'*32,'worldPlan':{'maps':[{'map':'Survival_1','partitions':[1],'memoryBytes':12*1024**3,'initialReplicas':1}]},'services':{'game-1':{'id':'owned'}}}
        engine=Mock(spec=manager.Engine);engine.assert_owned.return_value={'State':{'Status':'running'},'HostConfig':{'Memory':12*1024**3}}
        with patch.object(manager,'save'),patch.object(manager.Path,'read_text',return_value='MemTotal: 41943040 kB\nMemAvailable: 20971520 kB\n'):
            result=manager.set_map_memory(state,engine,'Survival_1',16)
        self.assertEqual(result['memoryGiB'],16);self.assertFalse(result['restartRequired'])
        self.assertEqual(state['mapMemoryOverrides']['Survival_1'],16*1024**3)
        self.assertEqual(state['worldPlan']['initialMemoryBytes'],16*1024**3)
        self.assertNotIn('pendingMemoryChange',state)
        engine.set_component_memory.assert_called_once_with('owned','a'*32,'game-1',16*1024**3)
        engine.lifecycle.assert_not_called()

    def test_live_memory_decrease_is_rejected_and_failed_increase_keeps_recoverable_intent(self):
        state={'id':'a'*32,'worldPlan':{'maps':[{'map':'Survival_1','partitions':[1],'memoryBytes':12*1024**3,'initialReplicas':1}]},'services':{'game-1':{'id':'owned'}}}
        engine=Mock(spec=manager.Engine);engine.assert_owned.return_value={'State':{'Status':'running'},'HostConfig':{'Memory':12*1024**3}}
        with patch.object(manager,'save'),patch.object(manager.Path,'read_text',return_value='MemTotal: 41943040 kB\nMemAvailable: 20971520 kB\n'):
            with self.assertRaisesRegex(ValueError,'Stop the map'):manager.set_map_memory(state,engine,'Survival_1',8)
            engine.set_component_memory.side_effect=manager.EngineError('Interrupted update')
            with self.assertRaises(manager.EngineError):manager.set_map_memory(state,engine,'Survival_1',16)
        self.assertEqual(state['pendingMemoryChange'],{'map':'Survival_1','bytes':16*1024**3})
        self.assertNotIn('mapMemoryOverrides',state)

    def test_memory_choice_is_persisted_without_starting_or_stopping_any_container(self):
        state={'id':'a'*32};engine=Mock()
        template={'world':{'spec':{'utilities':{'director':{'spec':{'configFiles':{'files':{'director.ini':'[ DeepDesert_1 ]\nMinServers=0\n[ Story ]\nEnableAutomaticInstanceScaling=true\n'}}}}}}}}
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'read_template',return_value=template),patch.object(manager,'save') as save:
            self.assertTrue(manager.dispatch({'action':'memory.policy'},engine)['enabled'])
            result=manager.dispatch({'action':'memory.policy.set','enabled':False},engine)
            self.assertFalse(result['enabled']);self.assertEqual(state['classicAutomaticMaps'],['Story'])
            save.assert_called_once_with(state)
            self.assertFalse(manager.dispatch({'action':'memory.policy'},engine)['enabled'])
            with self.assertRaises(ValueError):manager.dispatch({'action':'memory.policy.set','enabled':'false'},engine)
        engine.lifecycle.assert_not_called()

    def test_classic_memory_mode_retains_an_ordinary_started_map_without_dispatching_a_stop(self):
        state={'id':'a'*32,'worldId':'sh-fixture','desiredState':'running','memoryBalancingEnabled':False,
               'scaler':{'coreAdapterApplied':True},'mapTargets':{'game-3':'running'},
               'worldPlan':{'maps':[{'map':'SH_Arrakeen','partitions':[3],'initialReplicas':0}]}}
        patch_value=[{'op':'replace','path':'/spec/replicas','value':0},{'op':'replace','path':'/spec/partitions','value':[]}]
        with patch('manager.threading.Thread') as thread:
            result=manager.request_scale(state,FakeEngine(),'sh-fixture-sh-arrakeen',patch_value)
        self.assertEqual(result['spec']['partitions'],[3]);thread.assert_not_called()

    def test_classic_memory_mode_honors_explicit_warm_off_and_stock_automatic_maps(self):
        for extra in ({'manualPins':{'game-3':False}},{'classicAutomaticMaps':['SH_Arrakeen']}):
            state={'id':'a'*32,'worldId':'sh-fixture','desiredState':'running','memoryBalancingEnabled':False,
                   'scaler':{'coreAdapterApplied':True},'mapTargets':{'game-3':'running'},
                   'worldPlan':{'maps':[{'map':'SH_Arrakeen','partitions':[3],'initialReplicas':0}]},**extra}
            patch_value=[{'op':'replace','path':'/spec/replicas','value':0},{'op':'replace','path':'/spec/partitions','value':[]}]
            with patch.object(manager,'public_state',return_value={'services':[{'component':'game-3','state':'running','players':0}]}),patch.object(manager,'save'),patch('manager.threading.Thread') as thread:
                result=manager.request_scale(state,FakeEngine(),'sh-fixture-sh-arrakeen',patch_value)
            self.assertEqual(result['spec']['partitions'],[]);thread.return_value.start.assert_called_once()

    def test_version_read_is_allowed_during_operations_and_never_saves_state(self):
        with patch.object(manager,'project_state',return_value={'operation':{'phase':'running'}}),patch.object(manager,'installed_version',return_value={'appId':'4754530','installedBuild':'120'}),patch.object(manager,'save') as save:
            self.assertEqual(manager.dispatch({'action':'assets.version'},FakeEngine())['installedBuild'],'120')
            save.assert_not_called()

    def test_scheduled_restart_identity_is_persisted_before_background_dispatch(self):
        state={'id':'a'*32}
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'save') as save,\
             patch.object(manager,'public_state',side_effect=lambda value,engine:value),patch('manager.threading.Thread') as thread:
            reply=manager.dispatch({'action':'services.restart','requestId':'b'*32},FakeEngine())
            self.assertEqual(reply['operation']['requestId'],'b'*32)
            save.assert_called_once_with(state);thread.return_value.start.assert_called_once()
        for action,request_id in [('services.restart','invalid'),('services.stop','b'*32),('services.restart',[] )]:
            state={'id':'a'*32}
            with patch.object(manager,'project_state',return_value=state),patch.object(manager,'save') as save:
                with self.assertRaisesRegex(ValueError,'request identity'):manager.dispatch({'action':action,'requestId':request_id},FakeEngine())
                save.assert_not_called();self.assertNotIn('operation',state)
        state={'id':'a'*32,'backups':{'fixture':{'phase':'running'}}}
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'save') as save:
            with self.assertRaises(manager.OperationBusyError):manager.dispatch({'action':'services.restart','requestId':'b'*32},FakeEngine())
            save.assert_not_called();self.assertNotIn('operation',state)

    def test_party_sharing_persists_only_its_ini_setting_without_restarting_services(self):
        state={'id':'a'*32,'services':{'director':{'id':'own-director'}},'scaler':{'id':'own-scaler'}}
        engine=FakeEngine();engine.upload_component_files=Mock();engine.lifecycle=Mock()
        source='[ CB_Story_DestroyedZanovar ]\nMinServers=0\nNumExtraServers=0\n'
        with patch.object(manager,'map_policy',return_value={'ini':source}):
            result=manager.set_party_sharing(state,engine,'CB_Story_DestroyedZanovar',False)
        self.assertFalse(result['sharedParties'])
        self.assertEqual(state['directorIni'],'[ CB_Story_DestroyedZanovar ]\nMaxParties=1\nMinServers=0\nNumExtraServers=0\n')
        self.assertEqual(result['applyDelaySeconds'],60)
        engine.lifecycle.assert_not_called()
        with self.assertRaises(ValueError):manager.set_party_sharing(state,engine,'other',True)
    def test_map_restart_preserves_policy_and_reuses_native_admission(self):
        state={'id':'a'*32,'desiredState':'running','services':{'game-1':{'id':'own-game'}},
               'manualPins':{'game-1':False},'mapTargets':{'game-1':'running'}}
        engine=FakeEngine();engine.lifecycle=Mock()
        with patch.object(manager,'control_map') as control:
            result=manager.restart_map(state,engine,1,True)
            control.assert_called_once_with(state,engine,1,True,force=True,automatic=True)
        self.assertEqual(result,{'noop':False,'restarted':1})
        self.assertEqual(state['manualPins'],{'game-1':False})
        self.assertEqual(state['mapTargets'],{'game-1':'running'})
        engine.lifecycle.assert_called_once_with('own-game','a'*32,'stop')

    def test_map_restart_never_starts_a_cold_map_or_an_unlisted_partition(self):
        state={'id':'a'*32,'desiredState':'running','services':{}}
        with patch.object(manager,'control_map') as control:
            self.assertEqual(manager.restart_map(state,FakeEngine(),8),{'noop':True,'restarted':0})
            with self.assertRaises(ValueError):manager.restart_map(state,FakeEngine(),2)
            control.assert_not_called()

    def test_map_restart_retains_an_implicit_core_map_target(self):
        state={'id':'a'*32,'desiredState':'running','services':{'game-1':{'id':'own-game'}},'mapTargets':{}}
        engine=FakeEngine();engine.lifecycle=Mock()
        def start(*args,**kwargs):state['mapTargets']['game-1']='running'
        with patch.object(manager,'control_map',side_effect=start):manager.restart_map(state,engine,1,True)
        self.assertEqual(state['mapTargets'],{})

    def test_map_restart_requires_confirmation_for_occupied_or_unknown_maps(self):
        state={'id':'a'*32,'desiredState':'running','services':{'game-1':{'id':'own-game'}}}
        engine=FakeEngine();engine.lifecycle=Mock()
        for count in [None,2]:
            with patch.object(manager,'public_state',return_value={'services':[{'component':'game-1','players':count}]}):
                with self.assertRaisesRegex(ValueError,'Confirm the restart'):manager.restart_map(state,engine,1)
        engine.lifecycle.assert_not_called()

    def test_scaler_identity_cannot_use_database_credentials_or_general_management_actions(self):
        for action in ['scale.get','scale.patch']:manager.authorize_peer(10002,action)
        for action in ['status','credentials.save','database.create','backups.restore','rmq.publish','services.stop']:
            with self.assertRaises(ValueError):manager.authorize_peer(10002,action)
        with self.assertRaises(ValueError):manager.authorize_peer(12345,'scale.get')
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.state_patch=patch.object(manager,'STATE',self.root)
        self.state_patch.start()
    def tearDown(self): self.state_patch.stop();self.temp.cleanup()

    def test_project_identity_is_persisted_before_any_provisioning(self):
        first=manager.project_state(); second=manager.project_state()
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(len(first['id']),32)

    def test_ambiguous_database_create_is_not_repeated(self):
        state=manager.project_state(); engine=FakeEngine()
        assets={'state':'downloaded','images':[{'archive':'prerequisites/igw-postgres.tar','tags':['registry.funcom.com/funcom/self-hosting/igw-postgres:test']}]}
        with patch.object(manager,'assets_state',return_value=assets):
            with self.assertRaises(RuntimeError): manager.provision_database(state,engine,18932)
            self.assertEqual(manager.project_state()['phase'],'database-create-needs-recovery')
            with self.assertRaises(ValueError): manager.provision_database(manager.project_state(),engine,18932)
        self.assertEqual(engine.creates,1)

    def test_initialize_waits_for_health_before_any_sql(self):
        state=manager.project_state(); state['database']={'id':'own','name':'own','port':18932};state['phase']='database-starting'
        engine=FakeEngine();engine.health='starting'
        with self.assertRaises(ValueError): manager.initialize_database(state,engine)
        self.assertEqual(engine.execs,[])

    def test_status_never_returns_secrets_or_private_state(self):
        state=manager.project_state();state['privatePassword']='secret-value'
        (self.root/'postgres-admin.password').write_text('secret-value')
        with patch.object(manager,'assets_state',return_value={'state':'not-installed','images':[]}):
            public=manager.public_state(state,FakeEngine())
        self.assertNotIn('secret-value',json.dumps(public))
        self.assertNotIn('privatePassword',public)

    def test_public_database_scope_changes_with_owned_instance_and_backup_keeps_operation_binding(self):
        state=manager.project_state();state['database']={'id':'first-owned-pg','name':'owned-postgres','port':18932}
        state['backups']={'a'*32:{'name':'backup-1234-abcdef12.dump','phase':'completed','createdAt':1,'operationId':'b'*32}}
        with patch.object(manager,'assets_state',return_value={'state':'not-installed','images':[]}):
            first=manager.public_state(state,FakeEngine())
            state['database']['id']='second-owned-pg'
            second=manager.public_state(state,FakeEngine())
        self.assertNotEqual(first['database']['instanceId'],second['database']['instanceId'])
        self.assertNotIn('id',first['database'])
        self.assertEqual(first['backups'][0]['operationId'],'b'*32)

    def test_generic_container_commands_and_bad_credentials_are_rejected(self):
        with self.assertRaises(ValueError): manager.dispatch({'action':'container.stop','id':'existing-user-server'},FakeEngine())
        with self.assertRaises(ValueError): manager.dispatch({'action':'credentials.save','token':'x'*30+'\n'},FakeEngine())
        self.assertFalse((self.root/'funcom-token').exists())

    def test_long_operation_keeps_status_available_and_rejects_duplicate_dispatch(self):
        entered=threading.Event();release=threading.Event();calls=[]
        def slow_operation(state,engine):
            calls.append(state['id']);entered.set();release.wait(timeout=5)
        try:
            with patch.object(manager,'prepare_connections',side_effect=slow_operation):
                reply=manager.dispatch({'action':'connections.prepare'},FakeEngine())
                self.assertEqual(reply['operation']['phase'],'running')
                self.assertTrue(entered.wait(timeout=2))
                status=manager.dispatch({'action':'status'},FakeEngine())
                self.assertEqual(status['operation']['id'],reply['operation']['id'])
                with self.assertRaises(ValueError):manager.dispatch({'action':'connections.prepare'},FakeEngine())
                self.assertEqual(len(calls),1)
                release.set()
                deadline=time.monotonic()+5
                while manager.project_state()['operation']['phase']=='running' and time.monotonic()<deadline:time.sleep(.01)
                self.assertEqual(manager.project_state()['operation']['phase'],'completed')
        finally:release.set()

    def test_killed_backup_job_remains_visible_without_breaking_status_or_leaking_ids(self):
        class KilledBackup(FakeEngine):
            def assert_owned(self,*args):return {'State':{'Status':'exited','ExitCode':137}}
            def backup_report(self,*args):raise manager.EngineError('missing report')
        state=manager.project_state()
        state['backups']={'a'*32:{'name':'backup-12345678-abcdef12.dump','phase':'running','job':'private-job-identity','createdAt':1}}
        manager.save(state)
        result=manager.public_state(state,KilledBackup())
        self.assertEqual(result['backups'][0]['phase'],'failed')
        self.assertNotIn('private-job-identity',json.dumps(result))
        self.assertIn('preserved',result['backups'][0]['error'])

    def test_restore_recovery_blocks_unrelated_mutations(self):
        state=manager.project_state();state['restore']={'phase':'recovery-required'};manager.save(state)
        with self.assertRaisesRegex(ValueError,'interrupted database restore'):
            manager.dispatch({'action':'services.start'},FakeEngine())

    def test_restart_finishes_the_existing_restore_instead_of_creating_another(self):
        state=manager.project_state()
        state['restore']={'id':'a'*32,'name':'backup-1234-abcdef12.dump','job':'existing','resume':True,'startedAt':1}
        state['operation']={'phase':'running'}
        class FinishedRestore(FakeEngine):
            def assert_owned(self,*args):return {'State':{'Status':'exited','ExitCode':0}}
            def backup_report(self,*args):return {'operationId':'a'*32,'target':'dune','name':'backup-1234-abcdef12.dump','phase':'completed','ok':True}
        with patch.object(manager,'CONFIG',self.root/'config'),patch.object(manager,'start_services') as start,patch.object(manager,'public_state',return_value={}):
            manager.resume_interrupted_restore(state,FinishedRestore())
            start.assert_called_once()
            self.assertEqual(state['operation']['phase'],'completed')
            self.assertEqual(state['restore']['phase'],'completed')
            self.assertFalse(json.loads((self.root/'config/docker-maintenance.json').read_text())['active'])

    def test_map_admission_rejects_memory_pressure_before_creating_a_container(self):
        state=manager.project_state();state.update(desiredState='running',services={},worldPlan={
            'games':[{'partition':8,'map':'DeepDesert_1'}],'maps':[{'map':'DeepDesert_1','memoryBytes':15*1024**3}]})
        engine=FakeEngine();engine.create_component=Mock()
        with patch.object(manager,'Path') as path:
            path.return_value.read_text.return_value='MemAvailable: 1024 kB\nMemTotal: 65536 kB\n'
            with self.assertRaisesRegex(ValueError,'not enough memory'):manager.control_map(state,engine,8,True)
        engine.create_component.assert_not_called()

    def test_unknown_map_occupancy_requires_an_explicit_confirmed_stop(self):
        state=manager.project_state();state.update(desiredState='running',services={'game-8':{'id':'own-map','phase':'prepared'}},
            worldPlan={'games':[{'partition':8,'map':'DeepDesert_1'}],'maps':[{'map':'DeepDesert_1','initialReplicas':0}]})
        engine=FakeEngine();engine.lifecycle=Mock()
        with patch.object(manager,'public_state',return_value={'services':[{'component':'game-8','players':None}]}),patch.object(manager,'set_map_floor') as floor:
            with self.assertRaisesRegex(ValueError,'occupancy is unknown'):manager.control_map(state,engine,8,False)
            engine.lifecycle.assert_not_called()
            floor.assert_not_called()
            manager.control_map(state,engine,8,False,force=True)
            floor.assert_called_once_with(state,engine,'DeepDesert_1',False)
        engine.lifecycle.assert_called_once_with('own-map',state['id'],'stop')
        self.assertEqual(state['mapTargets']['game-8'],'stopped')

    def test_director_scaling_is_journaled_and_keeps_other_mutations_serial(self):
        state=manager.project_state();state.update(worldId='sh-fixture',desiredState='running',scaler={'coreAdapterApplied':True},
            services={},worldPlan={'maps':[{'map':'SH_Arrakeen','partitions':[3],'initialReplicas':0}]})
        entered=threading.Event();release=threading.Event()
        def slow_map(*args,**kwargs):entered.set();release.wait(5)
        patch_value=[{'op':'replace','path':'/spec/replicas','value':1},{'op':'replace','path':'/spec/partitions','value':[3]}]
        try:
            with patch.object(manager,'public_state',return_value={'services':[]}),patch.object(manager,'control_map',side_effect=slow_map) as control:
                reply=manager.request_scale(state,FakeEngine(),'sh-fixture-sh-arrakeen',patch_value)
                self.assertEqual(reply['spec']['partitions'],[3]);self.assertTrue(entered.wait(2))
                with self.assertRaisesRegex(ValueError,'in progress'):manager.dispatch({'action':'services.stop'},FakeEngine())
                release.set();deadline=time.monotonic()+5
                while manager.project_state()['operation']['phase']=='running' and time.monotonic()<deadline:time.sleep(.01)
                self.assertEqual(manager.project_state()['operation']['phase'],'completed')
                self.assertEqual(control.call_args.args[2:],(3,True));self.assertTrue(control.call_args.kwargs['automatic'])
        finally:release.set()

    def test_director_cannot_retire_a_pinned_or_unobserved_occupied_map(self):
        state=manager.project_state();state.update(worldId='sh-fixture',desiredState='running',scaler={'coreAdapterApplied':True},
            services={},memoryBalancingEnabled=True,mapTargets={'game-3':'running'},worldPlan={'maps':[{'map':'SH_Arrakeen','partitions':[3],'initialReplicas':0}]})
        value=[{'op':'replace','path':'/spec/replicas','value':0},{'op':'replace','path':'/spec/partitions','value':[]}]
        with patch.object(manager,'public_state',return_value={'services':[{'component':'game-3','state':'running','players':None}]}):
            with self.assertRaisesRegex(ValueError,'occupancy is unknown'):manager.request_scale(state,FakeEngine(),'sh-fixture-sh-arrakeen',value)
        state['manualPins']={'game-3':True}
        with self.assertRaisesRegex(ValueError,'warm floor'):manager.request_scale(state,FakeEngine(),'sh-fixture-sh-arrakeen',value)
        self.assertEqual(state['mapTargets']['game-3'],'running')

    def test_interrupted_scale_reconciles_observed_containers_without_replaying(self):
        state=manager.project_state();state.update(services={'game-3':{'id':'own'}},
            mapTargets={'game-3':'stopped','game-4':'running'},
            scalePending={'phase':'running','availablePartitions':[3,4]})
        engine=FakeEngine()
        manager.recover_interrupted_scale(state,engine)
        self.assertEqual(state['mapTargets'],{'game-3':'running','game-4':'stopped'})
        self.assertEqual(state['scalePending']['phase'],'interrupted')
        self.assertEqual(engine.execs,[])

    def test_map_floor_updates_only_installed_optional_map_and_keeps_custom_ini(self):
        state=manager.project_state();state.update(services={'director':{'id':'director'}},worldId='sh-fixture',
            worldPlan={'maps':[{'map':'SH_Arrakeen','partitions':[3],'initialReplicas':0}]})
        engine=Mock();engine.read_director_config.return_value=b'[ SH_Arrakeen ]\nMaxParties=1\nMinServers=0\n'
        result=manager.set_map_floor(state,engine,'SH_Arrakeen',True)
        self.assertEqual(result['minServers'],1)
        uploaded=engine.upload_component_files.call_args.args[3]
        ini=next(iter(uploaded.values()))['data']
        self.assertIn('MaxParties=1',ini);self.assertIn('MinServers=1',ini)
        self.assertTrue(manager.project_state()['manualPins']['game-3'])
        for name,value in [('foreign',True),('SH_Arrakeen','true')]:
            with self.assertRaises(ValueError):manager.set_map_floor(state,engine,name,value)
        self.assertEqual(engine.upload_component_files.call_count,1)


if __name__=='__main__':unittest.main()
