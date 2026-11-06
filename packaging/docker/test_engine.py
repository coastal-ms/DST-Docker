import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import json
import struct
import time

spec = importlib.util.spec_from_file_location('engine', Path(__file__).with_name('engine.py'))
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


class RecordingEngine(engine.Engine):
    def __init__(self, labels=None): self.calls=[]; self.labels=labels or {}
    def request(self, method, path, body=None, expected=None, timeout=30):
        self.calls.append((method, path, body))
        if path.endswith('/json'): return {'Config': {'Labels': self.labels}}
        if '/containers/create?' in path: return {'Id': 'a' * 64}
        return {}


class EngineTests(unittest.TestCase):
    def test_migration_reconciliation_binds_the_full_operation_and_backup_before_reusing_a_job(self):
        project='a'*32;operation='b'*32;image='registry.funcom.com/funcom/self-hosting/seabass-server-db-utils:fixture'
        existing={'Id':'owned-job','Config':{'Image':image,'Labels':{'io.dst.managed':'true','io.dst.project':project,'io.dst.component':'db-migrate','io.dst.operation':operation,'io.dst.script-sha256':engine.hashlib.sha256(b'script').hexdigest()},
            'Env':['DST_DATABASE_HOST=database','DST_BACKUP_NAME=backup.dump','DST_OPERATION_ID='+operation]}}
        class Client(RecordingEngine):
            def request(self,*args,**kwargs):return existing
        client=Client()
        self.assertEqual(client.create_migration_job(project,image,'network','state','database','script','backup-volume','backup.dump',operation=operation),'owned-job')
        existing['State']={'Status':'created'}
        with patch.object(client,'upload_component_files') as upload:
            client.create_migration_job(project,image,'network','state','database','script','backup-volume','backup.dump',operation=operation)
            upload.assert_called_once()
        with self.assertRaisesRegex(ValueError,'different operation'):client.create_migration_job(project,image,'network','state','database','script','backup-volume','other.dump',operation=operation)
        existing['Config']['Labels']['io.dst.operation']='c'*32
        with self.assertRaisesRegex(ValueError,'different operation'):client.create_migration_job(project,image,'network','state','database','script','backup-volume','backup.dump',operation=operation)
    def test_package_switch_job_has_no_network_or_project_credentials_and_only_an_owned_asset_mount(self):
        class Client(RecordingEngine):
            def request(self,method,path,body=None,expected=None,timeout=30):
                if path.startswith('/volumes/'):return {'Labels':{'io.dst.managed':'true','io.dst.component':'official-assets'}}
                if path.startswith('/images/'):return {'Id':'sha256:helper','Config':{'Labels':{'io.dst.asset-activator':'true'}}}
                self.created=body;return {'Id':'switch-job'}
        client=Client();client.create_asset_activation_job('a'*32,'b'*32,'c'*32,'120','activate','owned-assets')
        spec=client.created
        self.assertEqual(spec['User'],'10001:10001');self.assertEqual(spec['HostConfig']['NetworkMode'],'none')
        self.assertEqual(spec['HostConfig']['Mounts'],[{'Type':'volume','Source':'owned-assets','Target':'/srv/dst'}])
        self.assertEqual(len(spec['Env']),3);self.assertTrue(spec['HostConfig']['ReadonlyRootfs'])
        self.assertEqual(spec['HostConfig']['CapDrop'],['ALL'])
        with self.assertRaises(ValueError):client.create_asset_activation_job('a'*32,'b'*32,'../active','120','activate','owned-assets')
    def test_an_expected_missing_resource_is_none_and_an_unexpected_404_is_an_error(self):
        class Response:
            status=404
            def read(self,*args):return b'{"message":"No such container"}'
        class Connection:
            def request(self,*args):pass
            def getresponse(self):return Response()
            def close(self):pass
        with patch.object(engine,'EngineConnection',return_value=Connection()):
            self.assertIsNone(engine.Engine().request('GET','/containers/absent/json',expected=(200,404)))
            with self.assertRaises(engine.EngineError):engine.Engine().request('GET','/containers/absent/json')
    def test_games_only_share_the_owned_user_settings_subdirectory(self):
        project='a'*32
        class SettingsEngine(RecordingEngine):
            def request(self,method,path,body=None,expected=None,timeout=30):
                self.calls.append((method,path,body))
                if path.startswith(('/networks/','/volumes/')):return {'Labels':{'io.dst.managed':'true','io.dst.project':project}}
                return {'Id':'owned-game'}
        client=SettingsEngine()
        volume={'name':'dst-'+project+'-game-1-saved','target':'/home/dune/server/DuneSandbox/Saved/UserSettings','subpath':'UserSettings'}
        def create(value):return client.create_component(project,'game-8','registry.funcom.com/funcom/self-hosting/seabass-server:test',
                              'dst-'+project+'-network',{},volumes=[value],map_name='DeepDesert_1')
        create(volume)
        spec=client.calls[-1][2]
        self.assertEqual(spec['HostConfig']['Mounts'][0]['VolumeOptions'],{'Subpath':'UserSettings'})
        for field,value in [('name','foreign-saved'),('target','/etc'),('subpath','../UserSettings')]:
            with self.assertRaises(ValueError):create({**volume,field:value})

    def test_map_reader_is_confined_to_its_owned_game_pid_namespace(self):
        project='a'*32
        class ReaderEngine(RecordingEngine):
            def request(self,method,path,body=None,expected=None,timeout=30):
                self.calls.append((method,path,body))
                if path.startswith('/containers/') and path.endswith('/json'):
                    return {'State':{'Status':'running'},'Config':{'Labels':{'io.dst.managed':'true','io.dst.project':project,'io.dst.component':'game-8'}}}
                if path.startswith('/volumes/'):return {'Labels':{'com.docker.compose.volume':'dst-map-control'}}
                if path.startswith('/images/'):return {'Config':{'Labels':{'io.dst.map-observer':'true'}}}
                if '/containers/create?' in path:return {'Id':'b'*64}
                return {}
        client=ReaderEngine();client.create_map_observer(project,8,'owned-game','preview_dst-map-control')
        spec=next(call[2] for call in client.calls if '/containers/create?' in call[1])
        self.assertEqual(spec['HostConfig']['PidMode'],'container:owned-game')
        self.assertEqual(spec['HostConfig']['NetworkMode'],'none')
        self.assertTrue(spec['HostConfig']['ReadonlyRootfs'])
        self.assertEqual(spec['HostConfig']['CapDrop'],['ALL'])
        self.assertEqual([mount['Target'] for mount in spec['HostConfig']['Mounts']],['/control'])
        self.assertNotIn('/var/run/docker.sock',json.dumps(spec))

    def test_map_reader_cannot_join_a_foreign_game_or_an_arbitrary_partition(self):
        client=RecordingEngine({'io.dst.managed':'true','io.dst.project':'foreign','io.dst.component':'game-8'})
        with self.assertRaises(engine.EngineError):client.create_map_observer('a'*32,8,'foreign-game','control')
        with self.assertRaises(ValueError):client.create_map_observer('a'*32,35,'game','control')
        self.assertFalse(any(call[0]=='POST' for call in client.calls))

    def test_foreign_and_unlabelled_containers_cannot_be_changed(self):
        for labels in [{}, {'io.dst.managed':'true','io.dst.project':'other'}]:
            client=RecordingEngine(labels)
            with self.assertRaises(engine.EngineError): client.lifecycle('existing-user-server', 'a'*32, 'stop')
            self.assertEqual([call[0] for call in client.calls], ['GET'])

    def test_only_typed_lifecycle_operations_are_supported(self):
        client=RecordingEngine()
        with self.assertRaises(ValueError): client.lifecycle('x','a'*32,'exec')
        self.assertEqual(client.calls,[])

    def test_component_and_identifier_checks_fail_closed(self):
        client=RecordingEngine({'io.dst.managed':'true','io.dst.project':'a'*32,'io.dst.component':'game'})
        with self.assertRaises(engine.EngineError): client.assert_owned('own','a'*32,'postgres')
        with self.assertRaises(ValueError): engine.Engine().inspect('../foreign/stop')

    def test_database_creation_is_namespaced_loopback_only_and_preserves_volumes(self):
        project='a'*32
        client=RecordingEngine({'io.dst.managed':'true','io.dst.project':project})
        result=client.create_database(project,'registry.funcom.com/funcom/self-hosting/igw-postgres:17-test',18932,'x'*48)
        spec=next(call[2] for call in client.calls if '/containers/create?' in call[1])
        self.assertEqual(spec['Labels']['io.dst.project'],project)
        self.assertEqual(spec['HostConfig']['PortBindings']['5432/tcp'][0]['HostIp'],'127.0.0.1')
        self.assertNotIn('AutoRemove',spec['HostConfig'])
        self.assertTrue(result['volume'].startswith('dst-'+project))
        self.assertFalse(any(call[0]=='DELETE' for call in client.calls))

    def test_arbitrary_images_ports_and_project_ids_are_rejected_before_docker(self):
        client=RecordingEngine()
        for project,image,port in [('bad','registry.funcom.com/funcom/self-hosting/igw-postgres:x',18932),
                                   ('a'*32,'attacker/image:latest',18932),
                                   ('a'*32,'registry.funcom.com/funcom/self-hosting/igw-postgres:x',True)]:
            with self.assertRaises(ValueError): client.create_database(project,image,port,'x'*48)
        self.assertEqual(client.calls,[])

    def test_existing_foreign_volume_is_rejected_without_mutation(self):
        class ForeignVolume(RecordingEngine):
            def request(self,method,path,body=None,expected=None):
                self.calls.append((method,path,body))
                return {'Name':'dst-'+'a'*32+'-postgres','Labels':{'io.dst.project':'foreign'}}
        client=ForeignVolume()
        with self.assertRaises(engine.EngineError):client.ensure_owned_volume('dst-'+'a'*32+'-postgres','a'*32,'postgres')
        self.assertEqual([call[0] for call in client.calls],['GET'])

    def test_core_component_rejects_host_network_and_foreign_image(self):
        client=RecordingEngine()
        for image,host in [('attacker/image:latest',False),('registry.funcom.com/funcom/self-hosting/seabass-server-rabbitmq:test',True)]:
            with self.assertRaises(ValueError):
                client.create_component('a'*32,'rmq-game',image,'dst-'+'a'*32+'-network',{},host_network=host)
        self.assertEqual(client.calls,[])

    def test_backup_jobs_reject_arbitrary_images_names_and_storage_before_mutation(self):
        client=RecordingEngine()
        project='a'*32
        arguments={'project':project,'image':'registry.funcom.com/funcom/self-hosting/seabass-server-db-utils:test',
                   'network':'dst-'+project+'-network','state_volume':'own-private-state','backup_volume':'dst-'+project+'-backups',
                   'script':'fixed job','mode':'create','name':'backup-12345678-abcdef12.dump'}
        for replacement in [{'image':'attacker/image:latest'},{'name':'../other.dump'},
                            {'backup_volume':'existing-redblink-data'},{'mode':'exec'},{'network':'foreign-network'},
                            {'mode':'verify','expected_sha':'not-a-checksum'}]:
            with self.assertRaises(ValueError):client.create_backup_job(**{**arguments,**replacement})
        self.assertEqual(client.calls,[])

    def test_game_heartbeats_are_fresh_and_return_no_login_or_player_identity(self):
        now=time.time()
        messages=[{'partitionId':1,'serverId':'A'*22,'reportTimestamp':now-5,'ready':True,'players':[{'name':'private-player','id':'private-id'}],'loginPassword':'private-password'},
                  {'partitionId':2,'reportTimestamp':now-100,'ready':True,'players':[]},
                  {'partitionId':3,'reportTimestamp':now-2,'ready':'false','players':[]}]
        data='\n'.join('Received server state: '+json.dumps(message) for message in messages).encode()
        raw=bytes([1,0,0,0])+struct.pack('>I',len(data))+data
        class Response:
            status=200
            def read(self,*args):return raw
        class Connection:
            def request(self,*args):pass
            def getresponse(self):return Response()
            def close(self):pass
        client=RecordingEngine({'io.dst.managed':'true','io.dst.project':'a'*32,'io.dst.component':'director'})
        with patch.object(engine,'EngineConnection',Connection):result=client.game_heartbeats('own','a'*32)
        self.assertEqual(set(result),{1})
        self.assertTrue(result[1]['ready']);self.assertEqual(result[1]['players'],1)
        self.assertEqual(result[1]['serverId'],'A'*22)
        self.assertNotIn('private-',json.dumps(result))

    def test_running_components_cannot_be_retired_or_deleted_for_an_update(self):
        class Running(RecordingEngine):
            def inspect(self,identifier):return {'Config':{'Labels':self.labels},'State':{'Status':'running'}}
        client=Running({'io.dst.managed':'true','io.dst.project':'a'*32,'io.dst.component':'game-1'})
        with self.assertRaises(engine.EngineError):client.retire_game_container('own','a'*32,'game-1')
        self.assertEqual(client.calls,[])


if __name__=='__main__': unittest.main()
