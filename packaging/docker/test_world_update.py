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

    def tank_update(self):
        self.s['regisSupport']={'enabled':True,'image':'old-tank-image'}
        def prepare(plan):
            self.assertFalse(self.rt.running);self.assertFalse(self.rt.gateway)
            self.assertEqual(self.rt.package,'new');self.assertEqual(self.rt.schema,'old')
            self.s['regisSupport']={'enabled':True,'image':'new-tank-image'}
        self.controller.prepare_tanks=prepare
        self.controller.validate_tank_plan=lambda plan:None

    def test_tank_update_prepares_compatibility_before_migration_and_preserves_opt_in(self):
        self.tank_update()
        result=self.controller.apply('121',with_tanks=True)
        self.assertTrue(result['updated']);self.assertTrue(self.s['updateRun']['withTanks'])
        self.assertEqual(self.s['regisSupport']['image'],'new-tank-image')
        self.assertEqual(self.s['updateRun']['previous']['regisSupport']['image'],'old-tank-image')

    def test_unsupported_tank_build_aborts_before_stopping_or_backup(self):
        self.tank_update()
        self.controller.validate_tank_plan=lambda plan:(_ for _ in ()).throw(ValueError('unsupported Tank recipe'))
        with self.assertRaisesRegex(ValueError,'unsupported Tank recipe'):self.controller.apply('121',with_tanks=True)
        self.assertTrue(self.rt.running);self.assertTrue(self.rt.gateway)
        self.assertEqual(self.s['regisSupport']['image'],'old-tank-image');self.assertEqual(self.s['backups'],{})
        self.assertEqual(self.s['updateRun']['phase'],'failed-preflight')

    def test_failed_tank_generation_restores_original_package_and_compatibility_without_migrating(self):
        self.tank_update()
        self.controller.prepare_tanks=lambda plan:(_ for _ in ()).throw(ValueError('Tank utility failed'))
        with self.assertRaisesRegex(ValueError,'previous version was restored'):self.controller.apply('121',with_tanks=True)
        self.assertEqual(self.rt.package,'old');self.assertEqual(self.rt.schema,'old');self.assertEqual(self.rt.restores,0)
        self.assertEqual(self.s['regisSupport']['image'],'old-tank-image');self.assertTrue(self.rt.running)

    def test_migration_failure_restores_old_tank_policy_with_old_database_and_containers(self):
        self.tank_update();self.rt.fault='migration'
        with self.assertRaisesRegex(ValueError,'previous version was restored'):self.controller.apply('121',with_tanks=True)
        self.assertEqual(self.s['regisSupport']['image'],'old-tank-image');self.assertEqual(self.rt.restores,1)
        self.assertEqual(self.rt.package,'old');self.assertEqual(self.rt.generation,'old');self.assertTrue(self.rt.running)

    def test_stopped_tank_update_never_starts_a_game(self):
        self.tank_update();self.s['desiredState']='stopped';self.rt.running=False;self.rt.gateway=False
        self.assertFalse(self.controller.apply('121',with_tanks=True)['running'])
        self.assertFalse(self.rt.running);self.assertFalse(self.rt.gateway)
        self.assertEqual(self.s['regisSupport']['image'],'new-tank-image')

    def test_tank_flag_requires_a_json_boolean_before_any_update_journal(self):
        for value in ('true',1,None):
            with self.assertRaisesRegex(ValueError,'Invalid update request'):self.controller.apply('121',with_tanks=value)
            self.assertNotIn('updateRun',self.s)

    def test_tank_plan_preflight_accepts_only_a_packaged_recipe_and_official_game_tag(self):
        recipes=Path(__file__).resolve().parents[2]/'app/resources/regis-tanks'
        with patch.object(world_update.regis_artifacts,'RECIPES',recipes):
            world_update.NativeUpdate.validate_tank_plan(self.controller,{'images':{'game':{'image':'registry.funcom.com/funcom/self-hosting/seabass-server:2173753-0-shipping'}}})
            for image in ('registry.funcom.com/funcom/self-hosting/seabass-server:9999999-0-shipping','custom/game:2173753'):
                with self.assertRaisesRegex(ValueError,'no accepted Tank recipe'):
                    world_update.NativeUpdate.validate_tank_plan(self.controller,{'images':{'game':{'image':image}}})

    def test_update_generation_applies_verified_tank_image_only_to_hagga_without_saved_defaults(self):
        plan={'network':'owned-network','games':[{'partition':1,'map':'Survival_1'},{'partition':8,'map':'DeepDesert_1'}],
              'maps':[{'partitions':[1,8],'initialReplicas':2}]}
        self.s['regisSupport']={'enabled':True,'image':'sha256:'+'e'*64}
        self.s['updateRun']={'id':'c'*32,'phase':'preparing-components','previous':{'directorIni':'source','services':{'game-1':{}} ,'worldPlan':{},'profile':{}}}
        self.controller.m.read_credentials=lambda state:{'tls':{'ca.pem':b'ca','cert.pem':b'cert'}}
        self.controller.e.request=lambda *args:{'IPAM':{'Config':[{'Gateway':'172.30.0.1'}]}}
        template={'world':{'spec':{'utilities':{'director':{'spec':{'configFiles':{'files':{'director.ini':'source'}}}}}}}}
        def game_spec(plan,partition,credentials,bridge,defaults):
            self.assertEqual(defaults,{})
            return {'volumes':[],'files':{}}
        def replace(state,engine,specs,*args,**kwargs):
            self.assertEqual(specs['game-1']['regis_image'],'sha256:'+'e'*64)
            self.assertNotIn('regis_image',specs['game-8'])
        with patch.object(world_update,'queue_spec',return_value={}),patch.object(world_update,'service_specs',return_value={'director':{'files':{'Tools/Battlegroups/Director/BattlegroupDirector/director_config.ini':{}}}}),patch.object(world_update,'game_spec',side_effect=game_spec),patch.object(world_update,'native_director_ini',return_value='native'),patch.object(world_update,'classic_automatic_maps',return_value=[]),patch.object(world_update.service_generations,'replace_generation',side_effect=replace):
            self.s['connections']={'rmq-game':{}}
            world_update.NativeUpdate.prepare_generation(self.controller,template,plan)
