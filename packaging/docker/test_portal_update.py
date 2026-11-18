import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import portal_update as update


class ProductUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        update.prepare(self.root)
        self.updater = update.Updater(self.root)
        self.updater.current = Mock(return_value='1.0.12')
        self.updater.source = Mock(return_value=self.root)
        self.updater.manager = Mock()
        self.selected = {'currentVersion': '1.0.12', 'latestVersion': '1.0.13', 'tag': 'v1.0.13',
                         'commit': 'a'*40, 'available': True, 'checkedAt': 10}

    def tearDown(self): self.temp.cleanup()

    def request(self):
        return {'action': 'install', 'tag': 'v1.0.13', 'commit': 'a'*40, 'confirmation': 'UPDATE DST DOCKER'}

    def test_numeric_comparison_does_not_offer_downgrades(self):
        self.assertGreater(update.version('1.0.12'), update.version('v1.0.9'))
        self.assertLess(update.version('1.0.12'), update.version('1.1.0'))
        for value in ['v1.0.13-preview', '../../x', '', 12]:
            with self.assertRaises(ValueError): update.version(value)

    @unittest.skipUnless(os.geteuid()==0,'Requires isolated root ownership fixture')
    def test_root_prepare_preserves_original_updater_account_access(self):
        os.chown(self.root,12345,12345)
        (self.root/'portal-update/operation.json').write_text('{}')
        (self.root/'portal-update/update.log').write_text('fixture')
        update.prepare(self.root)
        for name in ['portal-update','portal-update/operation.json','portal-update/update.log','update.compose.json']:
            self.assertEqual((self.root/name).stat().st_uid,12345,name)

    def test_update_directory_symlink_is_not_followed(self):
        import shutil
        shutil.rmtree(self.root/'portal-update')
        target=self.root/'outside';target.mkdir()
        (self.root/'portal-update').symlink_to(target,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symbolic link'):update.prepare(self.root)
        self.assertEqual(list(target.iterdir()),[])

    def test_check_is_cached_and_force_rechecks_commit(self):
        responses = [{'tag_name':'v1.0.13'}, {'object':{'type':'commit','sha':'a'*40}}]
        module = {'urllib':__import__('urllib.request', fromlist=['request']), 'Redirect':Mock(), 'token':Mock(return_value=''),
                  'download':Mock(side_effect=lambda *args: json.dumps(responses.pop(0)).encode())}
        # Keep real urllib module shape used by the embedded bootstrap.
        import urllib
        module['urllib'] = urllib
        with patch.object(update,'bootstrap',return_value=module), patch('urllib.request.build_opener'):
            self.assertTrue(self.updater.check()['available'])
            self.updater.check(); self.assertEqual(module['download'].call_count,2)
            responses.extend([{'tag_name':'v1.0.14'}, {'object':{'type':'commit','sha':'b'*40}}])
            self.assertEqual(self.updater.check(force=True)['commit'], 'b'*40)
        self.updater.current.return_value='1.0.20'
        self.assertFalse(self.updater.check()['available'])

    def test_changed_release_or_downgrade_never_starts_worker(self):
        self.updater.check=Mock(return_value={**self.selected,'commit':'b'*40})
        with self.assertRaisesRegex(ValueError,'changed'): self.updater.install(self.request())
        self.updater.manager.assert_not_called()
        self.updater.check.return_value={**self.selected,'available':False,'currentVersion':'1.0.14'}
        with self.assertRaisesRegex(ValueError,'older'): self.updater.install(self.request())

    def test_same_version_starts_redeploy_worker(self):
        selected = {**self.selected, 'currentVersion': '1.0.13', 'available': False}
        self.updater.check = Mock(return_value=selected)
        with patch('threading.Thread') as thread:
            result = self.updater.install(self.request())
            self.assertEqual(result['phase'], 'running')
            self.updater.manager.assert_called_once_with('portal-update.reserve', result['id'])
            thread.assert_called_once_with(target=self.updater.worker, args=(selected, result['id']), daemon=True)

    def test_confirmation_and_arbitrary_arguments_rejected(self):
        for request in [{**self.request(),'prefix':'/other'}, {**self.request(),'confirmation':''}]:
            with self.assertRaises(ValueError):self.updater.install(request)
        self.updater.manager.assert_not_called()

    def test_reserves_stopped_world_and_rejects_duplicate_install(self):
        self.updater.check=Mock(return_value=self.selected)
        with patch('threading.Thread') as thread:
            result=self.updater.install(self.request())
            self.assertEqual(result['phase'],'running')
            self.updater.manager.assert_called_once_with('portal-update.reserve',result['id'])
            thread.return_value.start.assert_called_once()
            with self.assertRaisesRegex(ValueError,'already running'):self.updater.install(self.request())

    def test_running_world_refusal_does_not_launch_installer(self):
        self.updater.check=Mock(return_value=self.selected)
        self.updater.manager.side_effect=ValueError('Stop the battlegroup')
        with patch('threading.Thread') as thread:
            with self.assertRaises(ValueError):self.updater.install(self.request())
            thread.assert_not_called()

    def test_worker_preserves_prefix_pins_release_and_checks_installed_version(self):
        self.updater.operation={'phase':'running','id':'c'*32}
        self.updater.current.return_value='1.0.13'
        with patch('subprocess.run',return_value=Mock(returncode=0)) as run, patch('os.execv') as reload:
            self.updater.worker(self.selected,'c'*32)
            reload.assert_called_once()
        command=run.call_args.args[0]
        self.assertEqual(command[-3:],['--prefix',str(self.root),'--non-interactive'])
        self.assertEqual(run.call_args.kwargs['env']['DST_EXPECTED_RELEASE_COMMIT'],'a'*40)
        self.assertEqual(self.updater.operation['phase'],'completed')
        self.updater.manager.assert_called_once_with('portal-update.release','c'*32)

    def test_failed_installer_or_version_mismatch_is_never_success(self):
        for result in [1,0]:
            with patch('subprocess.run',return_value=Mock(returncode=result)):
                self.updater.worker(self.selected,'c'*32)
            self.assertEqual(self.updater.operation['phase'],'failed')

    def test_check_failure_retains_operation_without_claiming_up_to_date(self):
        self.updater.check=Mock(side_effect=OSError('network unreachable'))
        self.updater.operation={'phase':'running'}
        result=self.updater.request({'action':'status'})
        self.assertFalse(result['available']);self.assertIn('GitHub',result['error'])
        self.assertEqual(result['operation']['phase'],'running')

    def test_registration_is_scoped_to_installation_and_original_account(self):
        import types
        account=types.SimpleNamespace(pw_name='fixture',pw_dir='/home/fixture')
        with patch.dict('sys.modules',{'pwd':types.SimpleNamespace(getpwuid=lambda uid:account)}), \
             patch.object(Path,'write_text') as write, patch('subprocess.run') as run:
            update.register(self.root)
        unit=write.call_args.args[0]
        self.assertIn('User=fixture',unit);self.assertIn('SupplementaryGroups=docker',unit)
        self.assertIn('current/packaging/docker/portal_update.py',unit.replace('\\','/').replace('//','/'))
        self.assertEqual(run.call_args_list[-2].args[0][:3],['systemctl','enable','--now'])
        self.assertEqual(run.call_args.args[0][:2],['systemctl','restart'])


if __name__ == '__main__': unittest.main()
