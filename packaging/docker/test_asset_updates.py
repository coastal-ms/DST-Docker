import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import asset_updates
from engine import Engine


class AssetUpdateTests(unittest.TestCase):
    def test_stage_admission_reserves_host_memory_and_checks_disk_before_downloading(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);mem=root/'meminfo'
            mem.write_text('MemAvailable: 1024 kB\n')
            with self.assertRaisesRegex(ValueError,'headroom'):asset_updates.check_headroom(root,mem)
            mem.write_text('MemAvailable: 41943040 kB\n')
            (root/'install-state.json').write_text(json.dumps({'images':[{'bytes':1024**3}]}))
            with patch.object(asset_updates.os,'statvfs',return_value=Mock(f_bavail=0,f_frsize=4096)):
                with self.assertRaisesRegex(ValueError,'disk space'):asset_updates.check_headroom(root,mem)

    def test_persists_the_stage_identity_and_job_before_start_and_reuses_the_existing_stage(self):
        state={'id':'a'*32};saved=[];engine=Mock()
        engine.inspect.return_value={'Mounts':[{'Destination':'/assets','Type':'volume','Name':'owned-assets'}]}
        engine.create_asset_stage_job.return_value='owned-job'
        engine.lifecycle.side_effect=lambda *args:self.assertEqual(saved[-1]['assetUpdate']['job'],'owned-job')
        def save(value):saved.append(json.loads(json.dumps(value)))
        with patch.dict(os.environ,{'HOSTNAME':'self'}),patch.object(asset_updates,'check_headroom'):
            first=asset_updates.start_stage(state,engine,'120',save)
            second=asset_updates.start_stage(state,engine,'120',save)
        self.assertEqual(first,second);self.assertEqual(saved[0]['assetUpdate']['phase'],'preparing')
        engine.create_asset_stage_job.assert_called_once()
        with self.assertRaises(ValueError):asset_updates.start_stage(state,engine,'121',save)

    def test_ready_requires_job_identity_exit_build_inventory_and_template_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);stage=root/'staged'/('b'*32)
            manifest=stage/'server/steamapps/appmanifest_4754530.acf';manifest.parent.mkdir(parents=True)
            manifest.write_text('"appid" "4754530"\n"buildid" "120"\n')
            (stage/'install-state.json').write_text(json.dumps({'state':'downloaded','images':[{'verified':True}]}))
            state={'id':'a'*32,'assetUpdate':{'id':'b'*32,'job':'owned','phase':'downloading','expectedBuild':'120'}}
            engine=Mock(spec=Engine);engine.assert_owned.return_value={'Config':{'Labels':{'io.dst.stage':'b'*32}},'State':{'Status':'exited','ExitCode':0}}
            with patch.object(asset_updates,'package_inventory',return_value=[{'verified':True}]),patch.object(asset_updates,'read_template',return_value={'sha256':'c'*64}):
                result,changed=asset_updates.observe_stage(state,engine,root)
            self.assertTrue(changed);self.assertEqual(result['phase'],'ready');self.assertNotIn('job',result)
            self.assertEqual(result['templateSha256'],'c'*64)

    def test_failed_job_does_not_activate_or_report_ready(self):
        state={'id':'a'*32,'assetUpdate':{'id':'b'*32,'job':'owned','phase':'downloading','expectedBuild':'120'}}
        engine=Mock(spec=Engine);engine.assert_owned.return_value={'Config':{'Labels':{'io.dst.stage':'b'*32}},'State':{'Status':'exited','ExitCode':137}}
        result,changed=asset_updates.observe_stage(state,engine)
        self.assertTrue(changed);self.assertEqual(result['phase'],'failed')
        self.assertNotIn('worldPlan',state)

    def test_exhausted_configuration_retries_return_the_fixed_actionable_error(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);stage=root/'staged'/('b'*32);stage.mkdir(parents=True)
            (stage/'install-state.json').write_text(json.dumps({'state':'failed','error':asset_updates.MISSING_CONFIGURATION}))
            state={'id':'a'*32,'assetUpdate':{'id':'b'*32,'job':'owned','phase':'downloading','expectedBuild':'120'}}
            engine=Mock(spec=Engine);engine.assert_owned.return_value={'Config':{'Labels':{'io.dst.stage':'b'*32}},'State':{'Status':'exited','ExitCode':1}}
            result,_=asset_updates.observe_stage(state,engine,root)
            self.assertEqual(result['error'],asset_updates.MISSING_CONFIGURATION)

    def test_exhausted_manifest_recovery_is_reported_without_activating_the_package(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);stage=root/'staged'/('b'*32);stage.mkdir(parents=True)
            (stage/'install-state.json').write_text(json.dumps({'state':'failed','error':asset_updates.MANIFEST_RECOVERY_FAILED}))
            state={'id':'a'*32,'assetUpdate':{'id':'b'*32,'job':'owned','phase':'downloading','expectedBuild':'120'}}
            engine=Mock(spec=Engine);engine.assert_owned.return_value={'Config':{'Labels':{'io.dst.stage':'b'*32}},'State':{'Status':'exited','ExitCode':1}}
            result,_=asset_updates.observe_stage(state,engine,root)
            self.assertEqual(result['phase'],'failed');self.assertEqual(result['error'],asset_updates.MANIFEST_RECOVERY_FAILED)
            self.assertNotIn('worldPlan',state)

    def test_download_container_receives_only_owned_asset_storage_and_fixed_installer_identity(self):
        class Client(Engine):
            def request(self,method,path,body=None,**kwargs):
                if path.startswith('/volumes/'):return {'Labels':{'io.dst.managed':'true','io.dst.component':'official-assets'}}
                if path.startswith('/images/'):return {'Id':'sha256:verified','Config':{'Labels':{'io.dst.asset-installer':'true'}}}
                self.created=body;return {'Id':'download-job'}
        client=Client();client.create_asset_stage_job('a'*32,'b'*32,'120','owned-assets')
        spec=client.created;self.assertEqual(spec['Image'],'sha256:verified')
        self.assertEqual(spec['User'],'10001:10001');self.assertTrue(spec['HostConfig']['ReadonlyRootfs'])
        self.assertEqual(spec['HostConfig']['Mounts'],[{'Type':'volume','Source':'owned-assets','Target':'/srv/dst'}])
        self.assertNotIn('PortBindings',spec['HostConfig'])
