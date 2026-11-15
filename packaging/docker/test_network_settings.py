import copy
import unittest
from unittest.mock import Mock,patch
import manager
import test_game_plan as fixtures


class NetworkSettingsTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.GamePlanTests();fixture.setUp()
        self.template=fixture.template
        self.template['world']['spec']['utilities']={'director':{'spec':{'configFiles':{'files':{'director.ini':'stock'}}}}}
        self.template['world']['spec']['utilities']['messageQueues']={'templates':[{'metadata':{'name':role},'spec':{'configs':{'system':'auth_backends.1 = $(RMQ_AUTH_BACKEND_1)\nauth_http.http_method = post\nauth_http.user_path = http://$(RMQ_HTTP_AUTH_ADDRESS)/auth/user'},'plugins':{'system':['rabbitmq_management','rabbitmq_prometheus','rabbitmq_auth_backend_http','rabbitmq_auth_backend_cache']}}} for role in ['admin','game']]}
        self.assets=fixture.assets
        self.state={'id':fixture.project,'phase':'database-ready','profile':fixture.profile,'worldPlan':fixture.plan(),
                    'database':fixture.database,'desiredState':'running',
                    'services':{name:{'id':name,'phase':'prepared'} for name in ['director','gateway','text-router','game-1','game-2','game-8']},
                    'connections':{name:{'id':name,'phase':'prepared'} for name in ['rmq-admin','rmq-game']},
                    'mapTargets':{'game-8':'stopped'},'mapModes':{'DeepDesert_1':'automatic'},
                    'mapMemoryOverrides':{'Survival_1':16*1024**3}}
        self.request={'mode':'public','address':'8.8.4.4','expectedAddress':'127.0.0.1'}

    def test_invalid_or_stale_settings_never_stop_the_world(self):
        for change in [{'mode':'invalid'},{'address':'192.168.1.20'},{'address':'239.1.1.1'},
                       {'address':'100.64.0.1'},{'address':'0.0.0.0'},{'address':'::1'},
                       {'address':'not-an-ip'},{'expectedAddress':'old'}, {'mode':'private','address':'8.8.4.4'}]:
            with self.subTest(change=change),patch.object(manager,'stop_services') as stop:
                with self.assertRaises(ValueError):manager.set_network(self.state,Mock(),{**self.request,**change})
                stop.assert_not_called()

    def test_address_and_standard_ports_propagate_to_every_component_without_changing_identity(self):
        for running in [True,False]:
            for address,mode in [('8.8.4.4','public'),('192.168.2.10','private')]:
                with self.subTest(running=running,mode=mode):
                    state=copy.deepcopy(self.state);state['desiredState']='running' if running else 'stopped'
                    request={**self.request,'address':address,'mode':mode}
                    credentials={'worldId':'sh-test-abcdef','token':'fixture','dbPassword':'fixture','apiKey':'fixture','rmqSecret':'fixture',
                                 'tls':{'ca.pem':b'CA','cert.pem':b'CERT','key.pem':b'KEY'}}
                    engine=Mock(spec=manager.Engine);engine.read_director_config.return_value='manual INI';engine.assert_owned.return_value={'State':{'Status':'exited'}}
                    engine.request.return_value={'IPAM':{'Config':[{'Gateway':'172.20.0.1'}]}}
                    def stopped(value,_engine):value['desiredState']='stopped'
                    with patch.object(manager,'save'),patch.object(manager,'public_state',return_value={}),patch.object(manager,'read_template',return_value=self.template),\
                         patch.object(manager,'assets_state',return_value=self.assets),patch.object(manager,'read_credentials',return_value=credentials),\
                         patch.object(manager,'stop_services',side_effect=stopped) as stop,patch.object(manager,'start_services') as start,\
                         patch.object(manager.service_generations,'replace_generation') as replace,\
                         patch.object(manager.service_generations,'commit_generation'),patch('core_services.Path.read_text',return_value='launcher'):
                        manager.set_network(state,engine,request)
                    stop.assert_called_once();self.assertEqual(start.call_count,int(running))
                    specs=replace.call_args.args[2]
                    self.assertEqual(state['profile']['address'],address)
                    self.assertEqual(state['worldPlan']['ports']['rmq-game'],31982)
                    self.assertEqual(state['worldPlan']['games'][0]['gamePort'],7777)
                    for name in ['director','gateway','text-router']:
                        self.assertEqual(specs[name]['environment']['HOST_DATACENTER_IP_ADDRESS'],address)
                    self.assertIn('--RMQGameHostname='+address,specs['gateway']['command'])
                    self.assertIn('--RMQGamePort=31982',specs['gateway']['command'])
                    self.assertEqual(specs['rmq-game']['ports'][0]['host'],31982)
                    for name in ['game-1','game-2','game-8']:
                        self.assertIn('-ExternalAddress='+address,specs[name]['command'])
                        self.assertIn('--RMQGamePort=31982',specs[name]['command'])
                    self.assertEqual(state['mapTargets'],self.state['mapTargets'])
                    self.assertEqual(state['mapModes'],self.state['mapModes'])
                    self.assertEqual(state['worldPlan']['maps'][0]['memoryBytes'],16*1024**3)
                    self.assertEqual(state['database'],self.state['database'])
                    self.assertEqual(specs['director']['files']['Tools/Battlegroups/Director/BattlegroupDirector/director_config.ini']['data'],'manual INI')

    def test_tls_certificate_uses_new_advertised_address(self):
        self.state['worldPlan']['profile']={**self.state['profile'],'address':'8.8.4.4'}
        with patch.object(manager,'ensure_tls',return_value={}) as tls,patch.object(manager.Path,'is_file',return_value=False):
            manager.tls_for_plan(self.state['worldPlan'])
        self.assertEqual(tls.call_args.args[2],'8.8.4.4')

    def test_legacy_plan_is_preserved_until_explicit_apply(self):
        self.assertEqual(self.state['worldPlan']['ports']['rmq-game'],29779)
        self.assertEqual(manager.validate_profile({'name':'Test','region':'Europe','address':'127.0.0.1'})['gamePortBase'],7777)

    def test_typed_dispatch_rejects_invalid_address_before_launching_a_worker(self):
        with patch.object(manager,'project_state',return_value=self.state),patch.object(manager,'save') as save,patch.object(manager.threading,'Thread') as thread:
            with self.assertRaises(ValueError):
                manager.dispatch({'action':'network.set',**self.request,'address':'192.168.1.6'},Mock(spec=manager.Engine))
            save.assert_not_called();thread.assert_not_called()

    def test_failed_reconfiguration_never_restarts_a_partial_generation(self):
        def stopped(state,engine):state['desiredState']='stopped'
        with patch.object(manager,'read_template',return_value=self.template),patch.object(manager,'assets_state',return_value=self.assets),patch.object(manager,'stop_services',side_effect=stopped),\
             patch.object(manager,'reconfigure_address',side_effect=ValueError('replacement failed')),patch.object(manager,'start_services') as start:
            with self.assertRaisesRegex(ValueError,'replacement failed'):manager.set_network(self.state,Mock(),self.request)
            start.assert_not_called()


if __name__=='__main__':unittest.main()
