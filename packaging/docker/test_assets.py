import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import assets


class AssetStagingTests(unittest.TestCase):
    def test_0x6_cleans_only_the_download_manifest_then_retries_the_same_command(self):
        for code in (0, 8):
            with self.subTest(exit_code=code), tempfile.TemporaryDirectory() as folder:
                root=Path(folder);stage=root/'staged'/'retry'
                (stage/'steam').mkdir(parents=True);(stage/'steam/steamcmd.sh').write_text('fixture')
                active=root/'server/steamapps';active.mkdir(parents=True)
                (active/'appmanifest_4754530.acf').write_text('active manifest')
                (root/'server/save.db').write_text('active save')
                target=stage/'server/steamapps';target.mkdir(parents=True)
                manifest=target/'appmanifest_4754530.acf';manifest.write_text('stale download manifest')
                (target/'appmanifest_999.acf').write_text('other app')
                (stage/'server/package.tar').write_text('downloaded package')
                calls=[]
                def download(command, **kwargs):
                    calls.append(command)
                    if len(calls)==1:
                        kwargs['stdout'].write("\x1b[0mError! App '4754530' state is 0x6 after update job.\n")
                        return Mock(returncode=code)
                    self.assertFalse(manifest.exists())
                    self.assertEqual(json.loads((stage/'install-state.json').read_text())['state'],'downloading')
                    manifest.write_text('"appid" "4754530"\n"buildid" "120"\n')
                    return Mock(returncode=0)
                with patch.object(assets,'package_inventory',return_value=[]),patch.object(assets.subprocess,'run',side_effect=download),patch.object(assets.time,'sleep') as sleep:
                    assets.install(stage,expected_build='120')
                self.assertEqual(len(calls),2);self.assertEqual(calls[0],calls[1]);sleep.assert_called_once_with(20)
                self.assertEqual((active/'appmanifest_4754530.acf').read_text(),'active manifest')
                self.assertEqual((root/'server/save.db').read_text(),'active save')
                self.assertEqual((target/'appmanifest_999.acf').read_text(),'other app')
                self.assertEqual((stage/'server/package.tar').read_text(),'downloaded package')
                self.assertEqual(json.loads((stage/'install-state.json').read_text())['installedBuild'],'120')
                self.assertIn('Retrying in 20 seconds (attempt 2 of 3)',(stage/'steam-install.log').read_text())

    def test_persistent_0x6_stops_after_three_attempts_and_keeps_the_final_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            stage=Path(folder);(stage/'steam').mkdir();(stage/'steam/steamcmd.sh').write_text('fixture')
            target=stage/'server/steamapps';target.mkdir(parents=True)
            manifest=target/'appmanifest_4754530.acf'
            def download(command, **kwargs):
                manifest.write_text('latest failure metadata')
                kwargs['stdout'].write("Error! App '4754530' state is 0x6 after update job.\n")
                return Mock(returncode=8)
            with patch.object(assets.subprocess,'run',side_effect=download) as run,patch.object(assets.time,'sleep') as sleep,patch.object(assets,'package_inventory') as inventory:
                with self.assertRaisesRegex(RuntimeError,'Automatic app-manifest cleanup and retry did not resolve'):
                    assets.install(stage,expected_build='120')
            self.assertEqual(run.call_count,3);self.assertEqual(sleep.call_args_list,[((20,),),((20,),)])
            inventory.assert_not_called();self.assertTrue(manifest.exists())
            self.assertEqual(json.loads((stage/'install-state.json').read_text())['error'],assets.MANIFEST_RECOVERY_FAILED)

    def test_a_missing_manifest_still_retries_but_a_new_error_does_not_reuse_old_0x6_output(self):
        with tempfile.TemporaryDirectory() as folder:
            stage=Path(folder);(stage/'steam').mkdir();(stage/'steam/steamcmd.sh').write_text('fixture')
            replies=iter(["Error! App '4754530' state is 0x6 after update job.", 'Disk full'])
            def download(command, **kwargs):
                kwargs['stdout'].write(next(replies)+'\n');return Mock(returncode=8)
            with patch.object(assets.subprocess,'run',side_effect=download) as run,patch.object(assets.time,'sleep') as sleep:
                with self.assertRaisesRegex(RuntimeError,'exited with code 8'):assets.install(stage)
            self.assertEqual(run.call_count,2);sleep.assert_called_once_with(20)
            self.assertIn('already absent',(stage/'steam-install.log').read_text())

    def test_other_apps_states_and_generic_0x6_mentions_do_not_remove_the_manifest(self):
        for output in ["Error! App '999' state is 0x6 after update job.",
                       "Error! App '4754530' state is 0x606 after update job.",
                       "Error! App '4754530' state is 0x6e after update job.",
                       'Troubleshooting: state is 0x6', 'Network failure']:
            with self.subTest(output=output),tempfile.TemporaryDirectory() as folder:
                stage=Path(folder);(stage/'steam').mkdir();(stage/'steam/steamcmd.sh').write_text('fixture')
                manifest=stage/'server/steamapps/appmanifest_4754530.acf';manifest.parent.mkdir(parents=True);manifest.write_text('keep')
                def download(command, **kwargs):
                    kwargs['stdout'].write(output+'\n');return Mock(returncode=8)
                with patch.object(assets.subprocess,'run',side_effect=download) as run,patch.object(assets.time,'sleep') as sleep:
                    with self.assertRaises(RuntimeError):assets.install(stage)
                run.assert_called_once();sleep.assert_not_called();self.assertEqual(manifest.read_text(),'keep')

    @unittest.skipIf(os.name=='nt','Linux installer path-link verification')
    def test_manifest_cleanup_refuses_links_to_the_active_package(self):
        for linked in ('server','steamapps','manifest'):
            with self.subTest(linked=linked),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);active=root/'active';active.mkdir();real=active/'appmanifest_4754530.acf';real.write_text('keep')
                stage=root/'stage';stage.mkdir()
                if linked=='server':(stage/'server').symlink_to(active,target_is_directory=True)
                else:
                    (stage/'server').mkdir()
                    if linked=='steamapps':(stage/'server/steamapps').symlink_to(active,target_is_directory=True)
                    else:
                        (stage/'server/steamapps').mkdir();(stage/'server/steamapps/appmanifest_4754530.acf').symlink_to(real)
                with self.assertRaisesRegex(ValueError,'not local'):assets.reset_app_manifest(stage)
                self.assertEqual(real.read_text(),'keep')

    def test_missing_configuration_is_retried_without_touching_the_active_package(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);stage=root/'staged'/'retry';(stage/'steam').mkdir(parents=True)
            (stage/'steam/steamcmd.sh').write_text('fixture')
            active=root/'server';active.mkdir();(active/'keep.ini').write_text('keep')
            calls=[]
            def download(command, **kwargs):
                calls.append(command)
                if len(calls)==1:
                    kwargs['stdout'].write("ERROR! Failed to install app '4754530' (Missing configuration)\n")
                    return Mock(returncode=8)
                manifest=stage/'server/steamapps/appmanifest_4754530.acf';manifest.parent.mkdir(parents=True)
                manifest.write_text('"appid" "4754530"\n"buildid" "120"\n')
                return Mock(returncode=0)
            with patch.object(assets,'package_inventory',return_value=[]),patch.object(assets.subprocess,'run',side_effect=download),patch.object(assets.time,'sleep'):
                assets.install(stage,expected_build='120')
            self.assertEqual(len(calls),2);self.assertEqual((active/'keep.ini').read_text(),'keep')
            self.assertIn('Missing configuration',(stage/'steam-install.log').read_text())

    def test_missing_configuration_retries_are_bounded_and_other_errors_are_not_retried(self):
        for error,code,expected_calls in [("ERROR! Failed to install app '4754530' (Missing configuration)",8,3),('Disk full',8,1),('Network failure',1,1)]:
            with self.subTest(error=error),tempfile.TemporaryDirectory() as folder:
                stage=Path(folder);(stage/'steam').mkdir();(stage/'steam/steamcmd.sh').write_text('fixture')
                def download(command, **kwargs):
                    kwargs['stdout'].write(error+'\n');return Mock(returncode=code)
                with patch.object(assets.subprocess,'run',side_effect=download) as run,patch.object(assets.time,'sleep'):
                    with self.assertRaises(RuntimeError):assets.install(stage,expected_build='120')
                self.assertEqual(run.call_count,expected_calls)
                self.assertEqual(json.loads((stage/'install-state.json').read_text())['state'],'failed')

    def test_download_stage_keeps_the_entire_active_tree_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);active=root/'server';active.mkdir()
            (active/'keep.ini').write_bytes(b'authoritative manual config')
            (root/'install-state.json').write_text('{"state":"downloaded","existing":true}')
            stage=root/'staged'/('a'*32)
            def download(command, **kwargs):
                self.assertIn(str(stage/'server'),command)
                manifest=stage/'server/steamapps/appmanifest_4754530.acf'
                manifest.parent.mkdir(parents=True)
                manifest.write_text('"appid" "4754530"\n"buildid" "120"\n')
                return Mock(returncode=0)
            (stage/'steam').mkdir(parents=True);(stage/'steam/steamcmd.sh').write_text('fixture')
            with patch.object(assets,'package_inventory',return_value=[{'archive':'verified'}]),patch.object(assets.subprocess,'run',side_effect=download):
                assets.install(stage,expected_build='120')
            self.assertEqual((active/'keep.ini').read_bytes(),b'authoritative manual config')
            self.assertEqual(json.loads((root/'install-state.json').read_text()),{'state':'downloaded','existing':True})
            self.assertEqual(json.loads((stage/'install-state.json').read_text())['installedBuild'],'120')

    def test_mismatched_build_fails_only_the_staged_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            stage=Path(folder)/'stage';(stage/'steam').mkdir(parents=True)
            (stage/'steam/steamcmd.sh').write_text('fixture')
            manifest=stage/'server/steamapps/appmanifest_4754530.acf';manifest.parent.mkdir(parents=True)
            manifest.write_text('"appid" "4754530"\n"buildid" "121"\n')
            with patch.object(assets,'package_inventory',return_value=[]),patch.object(assets.subprocess,'run',return_value=Mock(returncode=0)):
                with self.assertRaisesRegex(ValueError,'different build'): assets.install(stage,expected_build='120')
            self.assertEqual(json.loads((stage/'install-state.json').read_text())['state'],'failed')

    def test_stage_identity_is_validated_before_any_installer_write(self):
        for stage,build in [('../active','120'),('a'*32,'invalid'),('', '120')]:
            with patch.dict(os.environ,{'DST_ASSETS_STAGE_ID':stage,'DST_EXPECTED_BUILD':build}),patch.object(assets,'install') as install:
                with self.assertRaises(ValueError):assets.main()
                install.assert_not_called()
