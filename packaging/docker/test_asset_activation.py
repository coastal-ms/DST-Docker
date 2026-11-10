import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import fcntl
from asset_activation import change_package
from assets import package_inventory

STAGE='a'*32
ARCHIVES=['battlegroup/server.tar','battlegroup/server-bg-director.tar','battlegroup/server-gateway.tar',
          'battlegroup/server-text-router.tar','battlegroup/server-rabbitmq.tar','battlegroup/server-db-utils.tar','prerequisites/igw-postgres.tar']


def fixture(root):
    for server,build in [(root/'server','120'),(root/'staged'/STAGE/'server','121')]:
        manifest=server/'steamapps/appmanifest_4754530.acf';manifest.parent.mkdir(parents=True)
        manifest.write_text('"appid" "4754530"\n"buildid" "'+build+'"\n')
        config=server/'scripts/setup/config';config.mkdir(parents=True)
        for name in ['UserGame.ini','UserEngine.ini','UserServerCustomSettings.ini']:(config/name).write_text('fixture '+build)
        template={'kind':'BattleGroup','spec':{'database':{'template':{'spec':{'deployment':{'spec':{'worldPartitions':[
            {'map':'Survival_1','partitions':[{'id':1,'minX':0,'minY':0,'maxX':1,'maxY':1}]}]}}}}}}}
        path=server/'scripts/setup/templates/world-template.yaml';path.parent.mkdir();path.write_text(json.dumps(template))
        for name in ARCHIVES:
            path=server/'images'/name;path.parent.mkdir(parents=True,exist_ok=True)
            with tarfile.open(path,'w') as archive:
                data=json.dumps([{'RepoTags':['registry.funcom.com/funcom/self-hosting/fixture:'+build]}]).encode()
                member=tarfile.TarInfo('manifest.json');member.size=len(data);archive.addfile(member,io.BytesIO(data))
    old=b'{"state":"downloaded", "preserve":"exact original metadata"}\n'
    (root/'install-state.json').write_bytes(old)
    stage=root/'staged'/STAGE
    (stage/'install-state.json').write_text(json.dumps({'state':'downloaded','images':package_inventory(stage/'server')}))
    return old


class AssetActivationTests(unittest.TestCase):
    def test_a_second_activation_is_refused_while_the_global_package_lock_is_owned(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);original=fixture(root)
            with (root/'.dst-package-activation.lock').open('wb') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaisesRegex(ValueError,'in progress'):change_package(root,STAGE,'121')
            self.assertEqual((root/'install-state.json').read_bytes(),original)
            self.assertEqual(change_package(root,STAGE,'121')['phase'],'active')

    def test_activate_and_rollback_preserve_both_packages_and_exact_old_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);original=fixture(root)
            result=change_package(root,STAGE,'121');self.assertEqual(result['phase'],'active')
            self.assertIn('121',(root/'server/steamapps/appmanifest_4754530.acf').read_text())
            self.assertTrue((root/'previous'/STAGE/'server').is_dir())
            self.assertEqual(change_package(root,STAGE,'121')['phase'],'active')
            self.assertEqual(change_package(root,STAGE,'121','rollback')['phase'],'rolled-back')
            self.assertEqual((root/'install-state.json').read_bytes(),original)
            self.assertTrue((root/'staged'/STAGE/'server').is_dir())
            with self.assertRaisesRegex(ValueError,'rolled back'):change_package(root,STAGE,'121')

    def test_recovers_real_abrupt_process_exit_after_each_activation_rename_and_metadata_replace(self):
        for phase in ['after-retire','after-install','after-metadata']:
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);fixture(root)
                code="import os,sys;from asset_activation import change_package;change_package(sys.argv[1],sys.argv[2],'121',checkpoint=lambda phase:os._exit(137) if phase==sys.argv[3] else None)"
                result=subprocess.run([sys.executable,'-B','-c',code,str(root),STAGE,phase],check=False)
                self.assertEqual(result.returncode,137)
                self.assertEqual(change_package(root,STAGE,'121')['phase'],'active')
                self.assertEqual(change_package(root,STAGE,'121','rollback')['phase'],'rolled-back')

    def test_recovers_abrupt_rollback_without_reactivating_the_candidate(self):
        for phase in ['after-return','after-restore','after-old-metadata']:
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);original=fixture(root);change_package(root,STAGE,'121')
                code="import os,sys;from asset_activation import change_package;change_package(sys.argv[1],sys.argv[2],'121','rollback',checkpoint=lambda phase:os._exit(137) if phase==sys.argv[3] else None)"
                result=subprocess.run([sys.executable,'-B','-c',code,str(root),STAGE,phase],check=False)
                self.assertEqual(result.returncode,137)
                with self.assertRaisesRegex(ValueError,'rollback'):change_package(root,STAGE,'121')
                self.assertEqual(change_package(root,STAGE,'121','rollback')['phase'],'rolled-back')
                self.assertEqual((root/'install-state.json').read_bytes(),original)

    def test_conflicting_metadata_or_modified_package_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);fixture(root)
            def stop(phase):
                if phase=='after-retire':raise RuntimeError('fixture interruption')
            with self.assertRaises(RuntimeError):change_package(root,STAGE,'121',checkpoint=stop)
            (root/'install-state.json').write_text('manual replacement')
            with self.assertRaisesRegex(ValueError,'metadata changed'):change_package(root,STAGE,'121')
            self.assertFalse((root/'server').exists())

    def test_invalid_identity_and_symlink_storage_are_refused_before_active_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);original=fixture(root)
            with self.assertRaises(ValueError):change_package(root,'../active','121')
            (root/'previous').symlink_to(root/'staged',target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'storage'):change_package(root,STAGE,'121')
            self.assertEqual((root/'install-state.json').read_bytes(),original)
