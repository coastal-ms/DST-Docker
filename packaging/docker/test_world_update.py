import copy
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import world_update


class Runtime:
    def __init__(self):
        self.package='old';self.schema='old';self.generation='old';self.running=True;self.gateway=True
        self.data={'player':'Coastal','keystones':205};self.maintenance=False;self.restores=0;self.players=0;self.fault=None


class TransactionTests(unittest.TestCase):
    def test_readiness_requires_healthy_queues_database_and_all_required_core_components(self):
        self.s['updateRun']={'id':'c'*32,'phase':'checking-maps'}
        status={'services':[{'component':'director','state':'running'},{'component':'text-router','state':'running'},
            {'component':'game-1','state':'running','desiredState':'running','gameReady':True,'players':0}],
            'connectionServices':[{'health':'healthy'},{'health':'healthy'}],'database':{'health':'healthy'}}
        self.controller.m.public_state=lambda *args:status
        world_update.NativeUpdate.ready(self.controller,False)
        status['connectionServices'][0]['health']='unhealthy'
        with self.assertRaisesRegex(ValueError,'became unhealthy'):world_update.NativeUpdate.ready(self.controller,False)
        status['connectionServices'][0]['health']='healthy';status['services'][0]['state']='exited'
        with self.assertRaisesRegex(ValueError,'core component'):world_update.NativeUpdate.ready(self.controller,False)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.rt=Runtime()
        self.stage='b'*32;(self.root/'staged'/self.stage).mkdir(parents=True)
        (self.root/'staged'/self.stage/'install-state.json').write_text('{"images":[]}')
        old={'version':'old','games':[{'partition':1}],'maps':[]};new={**old,'version':'new'}
        self.s={'id':'a'*32,'phase':'database-ready','operation':{'id':'c'*32,'phase':'running'},'worldPlan':old,'profile':{},
            'services':{'director':{'id':'director-old','phase':'prepared'},'text-router':{'id':'router-old','phase':'prepared'},'gateway':{'id':'gateway-old','phase':'prepared'},'game-1':{'id':'game-old','phase':'prepared'}},
            'connections':{},'backups':{},'database':{},'desiredState':'running','assetUpdate':{'id':self.stage,'phase':'ready','expectedBuild':'121'}}
        rt=self.rt
        def snapshot(state,engine):return {'services':[{'component':name,'state':'running' if rt.running else 'exited','players':rt.players} for name in state['services']]}
        def stop(state,engine):rt.running=False;rt.gateway=False;state['desiredState']='stopped'
        def start(state,engine,publish_gateway=True):
            rt.running=True;rt.gateway=publish_gateway;state['desiredState']='running'
            if publish_gateway and rt.fault=='publish':rt.fault=None;rt.data['new-progress']=True;raise ValueError('Gateway repair needed')
        def restore(state,engine,identifier,confirmation,keep_maintenance=False):
            self.assertTrue(keep_maintenance);self.assertTrue(rt.maintenance);rt.restores+=1
            if rt.fault=='restore':raise ValueError('Restore needs review')
            rt.data=copy.deepcopy(rt.backup);rt.schema='old'
        host=types.SimpleNamespace(CONFIG=self.root/'config',save=lambda state:None,public_state=snapshot,stop_services=stop,start_services=start,restore_backup=restore)
        host.atomic=lambda path,data,*args:setattr(rt,'maintenance',json.loads(data)['active'])
        engine=types.SimpleNamespace(read_director_config=lambda *args:b'[ Example ]\nMinServers=1\n')
        outer=self
        class Controller(world_update.NativeUpdate):
            def backup(self):
                rt.backup=copy.deepcopy(rt.data);self.s['backups']['fresh']={'verification':{'phase':'completed','restored':{'players':1}}};self.phase('verifying-backup',backupId='fresh')
            def switch(self,mode):
                rt.package='new' if mode=='activate' else 'old'
                (outer.root/'staged'/outer.stage/'activation-state.json').write_text(json.dumps({'phase':'active' if mode=='activate' else 'rolled-back'}))
            def migrate(self):
                self.phase('migrating-schema',schemaMayHaveChanged=True);rt.schema='new'
                if rt.fault in {'migration','restore'}:rt.data['partial-schema-change']=True;raise ValueError('Official migration failed')
            def sql(self,query):return '1'
            def demote(self):pass
            def prepare_generation(self,template,plan):
                old=copy.deepcopy(self.s['services']);generation='d'*32
                self.s['generationChange']={'id':generation,'phase':'prepared','old':old,'previousPlan':copy.deepcopy(self.s['worldPlan']),'previousProfile':{}}
                self.run['generationId']=generation;self.s['worldPlan']=plan
                self.s['services']={name:{'id':name+'-new','phase':'prepared'} for name in old};rt.generation='new'
            def ready(self,published):
                outer.assertTrue(rt.running);outer.assertEqual(rt.gateway,published)
                if not published and rt.fault=='players':
                    self.phase(self.run['phase'],playersObserved=True);rt.data['new-progress']=True;raise ValueError('A map failed after player progress')
        self.controller=Controller(self.s,engine,host)
        def rollback(state,engine,persist):
            journal=state.pop('generationChange');state['services']=journal['old'];state['worldPlan']=journal['previousPlan'];rt.generation='old'
        real_path=Path
        self.patches=[patch.object(world_update,'Path',side_effect=lambda value: self.root/'staged' if str(value)=='/assets/staged' else real_path(value)),
            patch.object(world_update,'read_template',return_value={'partitions':[],'sha256':'fixture'}),patch.object(world_update,'plan_world',return_value=new),
            patch.object(world_update.service_generations,'rollback_generation',side_effect=rollback)]
        for item in self.patches:item.start()
    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()

    def test_success_commits_before_publication_and_keeps_player_data(self):
        result=self.controller.apply('121')
        self.assertTrue(result['updated']);self.assertEqual(self.s['updateRun']['phase'],'completed')
        self.assertEqual(self.rt.package,'new');self.assertEqual(self.rt.schema,'new');self.assertTrue(self.rt.gateway)
        self.assertEqual(self.rt.data,{'player':'Coastal','keystones':205});self.assertFalse(self.rt.maintenance)

    def test_migration_failure_restores_the_old_database_package_and_runtime(self):
        self.rt.fault='migration'
        with self.assertRaisesRegex(ValueError,'previous version was restored'):self.controller.apply('121')
        self.assertEqual(self.rt.schema,'old');self.assertEqual(self.rt.package,'old');self.assertEqual(self.rt.restores,1)
        self.assertEqual(self.rt.data,{'player':'Coastal','keystones':205});self.assertTrue(self.rt.running);self.assertTrue(self.rt.gateway)
        self.assertEqual(self.s['updateRun']['phase'],'rolled-back');self.assertFalse(self.rt.maintenance)

    def test_failed_restore_keeps_the_world_stopped_and_management_guarded(self):
        self.rt.fault='restore'
        with self.assertRaisesRegex(ValueError,'recovery needs review'):self.controller.apply('121')
        self.assertEqual(self.s['updateRun']['phase'],'recovery-required');self.assertFalse(self.rt.running);self.assertTrue(self.rt.maintenance)

    def test_unknown_occupancy_aborts_before_stopping_or_touching_the_world(self):
        self.rt.players=None
        with self.assertRaisesRegex(ValueError,'occupancy became unknown'):self.controller.apply('121')
        self.assertTrue(self.rt.running);self.assertEqual(self.rt.package,'old');self.assertEqual(self.rt.restores,0)
        self.assertEqual(self.s['updateRun']['phase'],'failed-preflight')

    def test_post_publication_failure_does_not_restore_over_possible_new_progress(self):
        self.rt.fault='publish'
        with self.assertRaisesRegex(ValueError,'possible new player progress'):self.controller.apply('121')
        self.assertEqual(self.rt.restores,0);self.assertTrue(self.rt.data['new-progress']);self.assertEqual(self.rt.schema,'new')
        self.controller.recover();self.assertEqual(self.s['updateRun']['phase'],'completed');self.assertFalse(self.rt.maintenance)

    def test_player_progress_before_commit_requires_review_instead_of_automatic_restore(self):
        self.rt.fault='players'
        with self.assertRaisesRegex(ValueError,'possible new player progress'):self.controller.apply('121')
        self.assertEqual(self.rt.restores,0);self.assertTrue(self.rt.data['new-progress']);self.assertEqual(self.s['updateRun']['phase'],'recovery-required')

    def test_an_intentionally_stopped_world_is_updated_without_starting_it(self):
        self.s['desiredState']='stopped';self.rt.running=False;self.rt.gateway=False
        result=self.controller.apply('121')
        self.assertFalse(result['running']);self.assertFalse(self.rt.running);self.assertFalse(self.rt.gateway)
