from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
from core_services import game_spec, service_specs


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.project='a'*32
        self.plan={'projectId':self.project,'profile':{'name':'World ; $() " quoted','region':'North America','address':'localhost'},
                   'databaseName':'dst-'+self.project+'-postgres','databasePort':18932,
                   'names':{'rmq-game':'own-game','rmq-admin':'own-admin'},'ports':{'director':29777,'rmq-game':29779,'rmq-admin':29778,'rmq-game-http':29780,'text-router':29781},
                   'games':[{'partition':1,'map':'Survival_1','gamePort':28777,'igwPort':30777}],
                   'maps':[{'map':'Survival_1','memoryBytes':12*1024**3}]}
        self.credentials={'worldId':'sh-test-abcdef','token':'test-secret-token','dbPassword':'test-db-secret',
                          'rmqSecret':'test-rmq-secret','apiKey':'test-api-key','tls':{'ca.pem':b'PUBLIC TEST CA'}}

    def test_native_arguments_preserve_whitespace_and_secrets_without_shell_flattening(self):
        with patch('core_services.Path.read_text',return_value='test launcher'):
            spec=game_spec(self.plan,1,self.credentials,'172.20.0.1',{'UserEngine.ini':'manual defaults'})
        self.assertIn('-FarmRegion=North America',spec['command'])
        self.assertIn('-DatabasePassword=test-db-secret',spec['command'])
        self.assertEqual(spec['environment']['BATTLEGROUP_TITLE'],'World ; $() " quoted')
        self.assertEqual(spec['entrypoint'],['/dst-game.sh'])
        self.assertTrue(spec['host_network'])
        self.assertTrue(spec['volumes'][0]['mustBeNew'])
        self.assertNotIn('test-secret-token',str(spec['files']))
        self.assertEqual(spec['memory'],12*1024**3)
        self.assertEqual(spec['environment']['RMQ_HTTP_TOKEN_AUTH_SECRET'],self.credentials['rmqSecret'])
        self.assertEqual(spec['environment']['fls-apikey'],self.credentials['apiKey'])

    def test_seeded_settings_directory_is_writable_before_any_game_start(self):
        with patch('core_services.Path.read_text',return_value='test launcher'):
            spec=game_spec(self.plan,1,self.credentials,'172.20.0.1',{'UserGame.ini':'stock'})
        root='home/dune/server/DuneSandbox/Saved/UserSettings'
        self.assertEqual(spec['files'][root],{'directory':True,'uid':1000,'gid':65534,'mode':0o700})
        self.assertEqual(spec['files'][root+'/UserGame.ini']['uid'],1000)

    def test_core_services_share_own_endpoints_identity_and_auth_material(self):
        template={'world':{'spec':{'utilities':{'director':{'spec':{'configFiles':{'files':{'director.ini':'stock configuration'}}}}}}}}
        specifications=service_specs(self.plan,template,self.credentials)
        self.assertEqual(set(specifications),{'director','text-router','gateway'})
        for component,spec in specifications.items():
            self.assertEqual(spec['environment']['BATTLEGROUP'],'sh-test-abcdef')
            self.assertEqual(spec['environment']['RMQ_HTTP_TOKEN_AUTH_SECRET'],'test-rmq-secret')
            self.assertNotIn('test-secret-token',str(spec['files']))
            self.assertNotIn('http://',spec['environment']['KUBERNETES_SERVICE_HOST'])
        self.assertEqual(specifications['director']['environment']['Database_address'],self.plan['databaseName']+':5432')
        self.assertEqual(specifications['director']['files']['Tools/Battlegroups/Director/BattlegroupDirector/director_config.ini']['data'],'stock configuration')

    def test_new_maps_mount_existing_global_settings_without_seeding_over_manual_edits(self):
        self.plan['games'].append({'partition':8,'map':'DeepDesert_1','gamePort':28784,'igwPort':30784})
        self.plan['maps'].append({'map':'DeepDesert_1','memoryBytes':15*1024**3})
        with patch('core_services.Path.read_text',return_value='test launcher'):
            spec=game_spec(self.plan,8,self.credentials,'172.20.0.1',{'UserEngine.ini':'must not overwrite manual INI'})
        self.assertFalse(any('UserEngine.ini' in name for name in spec['files']))
        self.assertEqual(spec['volumes'][1],{'name':'dst-'+self.project+'-game-1-saved',
                         'target':'/home/dune/server/DuneSandbox/Saved/UserSettings','subpath':'UserSettings'})

    def test_native_scaler_uses_its_private_endpoint_and_preserves_the_game_queue_trust(self):
        template={'world':{'spec':{'utilities':{'director':{'spec':{'configFiles':{'files':{'director.ini':'stock'}}}}}}}}
        self.credentials['scaler']={'hostname':'own-scaler','token':'scaler-fixture','ca':b'SCALER PUBLIC CA'}
        spec=service_specs(self.plan,template,self.credentials)['director']
        self.assertEqual(spec['environment']['KUBERNETES_SERVICE_HOST'],'own-scaler')
        self.assertEqual(spec['environment']['KUBERNETES_SERVICE_PORT'],'8443')
        self.assertEqual(spec['files']['run/secrets/kubernetes.io/serviceaccount/token']['data'],'scaler-fixture')
        self.assertEqual(spec['files']['run/secrets/kubernetes.io/serviceaccount/ca.crt']['data'],b'SCALER PUBLIC CA')
        self.assertEqual(spec['files']['usr/local/share/ca-certificates/dst-connection.crt']['data'],b'PUBLIC TEST CA')


if __name__=='__main__':unittest.main()
