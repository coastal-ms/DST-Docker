from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import manager
import settings_adapter


class SettingsAdapterTests(unittest.TestCase):
    def setUp(self):
        self.project='a'*32
        self.state={'id':self.project,'desiredState':'stopped','services':{'game-1':{'id':'owned-game','phase':'prepared'}}}
        self.engine=Mock(spec=['assert_owned','request'])
        self.engine.assert_owned.return_value={'State':{'Status':'exited'},'Mounts':[
            {'Type':'volume','Name':'dst-'+self.project+'-game-1-saved','Destination':'/home/dune/server/DuneSandbox/Saved'}]}
        def request(method,path,body=None):
            if path=='/volumes/control':return {'Labels':{'com.docker.compose.volume':'dst-map-control'}}
            if path.startswith('/volumes/'):return {'Labels':{'io.dst.managed':'true','io.dst.project':self.project}}
            if path.startswith('/images/'):return {'Id':'own-helper-image'}
            return {'Id':'settings-helper'}
        self.engine.request.side_effect=request

    def test_helper_cannot_execute_commands_join_networks_or_access_docker_socket(self):
        with tempfile.TemporaryDirectory() as temporary,patch('settings_adapter.Path',return_value=Path(temporary)),patch('settings_adapter.os.chown'):
            settings_adapter.create(self.state,self.engine,'control')
        spec=self.engine.request.call_args.args[2]
        self.assertEqual(spec['User'],'1000:10001')
        self.assertEqual(spec['HostConfig']['NetworkMode'],'none')
        self.assertTrue(spec['HostConfig']['ReadonlyRootfs'])
        self.assertTrue(spec['HostConfig']['Init'])
        self.assertEqual(spec['HostConfig']['CapDrop'],['ALL'])
        self.assertEqual([m['Target'] for m in spec['HostConfig']['Mounts']],['/saved','/control'])
        self.assertNotIn('docker.sock',str(spec))

    def test_foreign_saved_storage_and_control_volume_are_rejected(self):
        self.engine.assert_owned.return_value['Mounts'][0]['Name']='foreign-volume'
        with self.assertRaises(ValueError):settings_adapter.create(self.state,self.engine,'control')
        with self.assertRaises(ValueError):settings_adapter.create(self.state,self.engine,'foreign-control')

    def test_retail_writes_require_stopped_intent_and_every_game_process_stopped(self):
        request={'action':'settings.write','file':'server','raw':'x','revision':'a'*64,'expectedExists':True}
        with patch('manager.settings_client.request',return_value={'ok':True,'data':{'revision':'new'}}) as client:
            self.state['desiredState']='running'
            with self.assertRaises(ValueError):manager.write_settings(self.state,self.engine,request)
            self.state['desiredState']='stopped';self.engine.assert_owned.return_value['State']['Status']='running'
            with self.assertRaises(ValueError):manager.write_settings(self.state,self.engine,request)
            client.assert_not_called()
            self.engine.assert_owned.return_value['State']['Status']='exited'
            self.assertEqual(manager.write_settings(self.state,self.engine,request),{'revision':'new'})
            payload=client.call_args.args[0]
            self.assertEqual(payload,{**request,'action':'write'})

    def test_unsupported_settings_ids_and_service_failure_cannot_report_success(self):
        with patch('manager.settings_client.request',return_value={'ok':False,'conflict':True,'error':'Changed; refresh.'}) as client:
            with self.assertRaisesRegex(ValueError,'Changed'):manager.write_settings(self.state,self.engine,{'file':'game'})
            client.reset_mock()
            for key in ['../path',[],None]:
                with self.assertRaises(ValueError):manager.write_settings(self.state,self.engine,{'file':key})
            client.assert_not_called()

    def test_startup_payload_preserves_shared_normalization_and_cannot_include_secrets_or_more_commands(self):
        replies=[{'ok':True,'data':{'revision':'a'*64,'fileExists':False}}, {'ok':True,'data':{'changed':True}}]
        with patch('manager.settings_client.request',side_effect=replies) as client:
            result=manager.set_startup_settings(self.state,self.engine,{'Vehicle.MaxVehiclesPerPlayer':'20','Dune.DisableShieldOnShooting':'false'})
            self.assertTrue(result['Success'])
            self.assertEqual(client.call_args.args[0]['raw'],'Dune.DisableShieldOnShooting false,Vehicle.MaxVehiclesPerPlayer 20\n')
        for values in [{'Bgd.ServerLoginPassword':'private'},{'safe':'one,two'},{'safe':'quote"value'},{'safe':'two\nlines'},{'name,extra':'1'},[]]:
            with patch('manager.settings_client.request') as client:
                with self.assertRaises(ValueError):manager.set_startup_settings(self.state,self.engine,values)
                client.assert_not_called()

    def test_offline_read_starts_only_the_settings_helper_and_waits_for_its_socket(self):
        snapshot={'raw':'Manual=42\r\n','revision':'a'*64,'fileExists':True}
        self.state['settingsService']={'id':'owned-helper'}
        with patch('manager.prepare_settings_service') as prepare,patch('manager.settings_client.request',side_effect=[ConnectionRefusedError(),{'ok':True,'data':snapshot}]) as client,patch('manager.time.sleep'):
            self.assertEqual(manager.read_settings(self.state,self.engine,'game'),snapshot)
            prepare.assert_called_once_with(self.state,self.engine)
            self.assertEqual(client.call_count,2)
            self.assertEqual(client.call_args.args[0],{'action':'read','file':'game'})
        self.assertEqual(self.state['desiredState'],'stopped')

    def test_running_helper_is_reused_and_file_errors_are_not_retried(self):
        self.state['settingsService']={'id':'owned-helper'}
        self.engine.assert_owned.return_value['State']['Status']='running'
        with patch('manager.prepare_settings_service') as prepare,patch('manager.settings_client.request',return_value={'ok':False,'error':'Unsupported encoding.'}) as client:
            with self.assertRaisesRegex(ValueError,'Unsupported encoding'):manager.read_settings(self.state,self.engine,'game')
            prepare.assert_not_called();client.assert_called_once()

    def test_read_cannot_start_helper_during_busy_or_interrupted_world_operation(self):
        for guard in [{'operation':{'phase':'running'}},{'restore':{'phase':'recovery-required'}},{'pendingResourceChange':{'anything':True}}]:
            with patch('manager.project_state',return_value={**self.state,**guard}),patch('manager.prepare_settings_service') as prepare,patch('manager.settings_client.request') as client:
                with self.assertRaises(ValueError):manager.dispatch({'action':'settings.read','file':'game'},self.engine)
                prepare.assert_not_called();client.assert_not_called()

    def test_read_rejects_paths_before_start_and_bounds_socket_readiness_wait(self):
        with patch('manager.prepare_settings_service') as prepare,patch('manager.settings_client.request',side_effect=FileNotFoundError()) as client,patch('manager.time.monotonic',side_effect=[0,6]):
            for key in ['../game',None,[]]:
                with self.assertRaises(ValueError):manager.read_settings(self.state,self.engine,key)
            prepare.assert_not_called();client.assert_not_called()
            with self.assertRaisesRegex(ValueError,'did not become ready'):manager.read_settings(self.state,self.engine,'engine')
            prepare.assert_called_once();client.assert_called_once()


if __name__=='__main__':unittest.main()
