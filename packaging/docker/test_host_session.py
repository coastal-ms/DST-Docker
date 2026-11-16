import json
from pathlib import Path
import tempfile
import multiprocessing
import socket
import time
import io
from contextlib import redirect_stdout
import unittest
from unittest.mock import patch,Mock
import host_session as host

class HostSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'host-session').mkdir()
        (self.root/'host-session/config.json').write_text(json.dumps({'project':'fixture','distribution':'Ubuntu','source':'/home/test/current','composeFiles':['/home/test/current/compose.yaml']}))
        self.session=host.HostSession(self.root)
        self.session.owner_setup_required=Mock(return_value=False)
        self.session.windows_console_reachable=Mock(side_effect=lambda origin: '127.0.0.1' not in origin)
        self.session.network_info=Mock(return_value={'dockerIp':'192.168.1.5','wslIp':'172.25.1.2','networkingMode':'nat'})
        self.state={'projectId':'world','desiredState':'running','operation':{'phase':'completed'},'services':[],'backups':[]}
    def tearDown(self):self.temp.cleanup()
    def test_browser_choice_survives_new_session_and_config_refresh(self):
        self.session.browser_executable=Mock(return_value=r'C:\Program Files\Microsoft\Edge\Application\msedge.exe')
        with redirect_stdout(io.StringIO()):self.session.choose_browser(lambda _: '3')
        other=host.HostSession(self.root)
        other.owner_setup_required=Mock(return_value=False)
        self.assertEqual(other.browser_preference(),'edge')
        self.assertNotIn('browser',other.config)
        other.console_origin='http://172.25.1.2:8088'
        with patch.object(other,'browser_executable',return_value=r'C:\Program Files\Microsoft\Edge\Application\msedge.exe'),patch.object(host,'windows_script') as script:
            other.open_browser()
        command=script.call_args.args[0]
        self.assertIn("-FilePath 'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe'",command)
        self.assertIn("-ArgumentList 'http://172.25.1.2:8088/?_dst_launch=",command)
    def test_missing_browser_does_not_replace_saved_choice_or_open_default(self):
        host.write_json(self.session.directory/'browser.json',{'browser':'edge'})
        self.session.console_origin='http://172.25.1.2:8088'
        with patch.object(host,'windows_script',return_value='') as script:
            with self.assertRaisesRegex(ValueError,'not installed'):self.session.open_browser()
        self.assertEqual(script.call_count,1)
        with redirect_stdout(io.StringIO()),patch.object(self.session,'browser_executable',side_effect=ValueError('not installed')):
            with self.assertRaises(ValueError):self.session.choose_browser(lambda _: '2')
        self.assertEqual(self.session.browser_preference(),'edge')
    def test_default_cancel_and_invalid_browser_selection(self):
        self.assertEqual(self.session.browser_preference(),'default')
        with redirect_stdout(io.StringIO()):
            self.session.choose_browser(lambda _: '')
            with self.assertRaises(ValueError):self.session.choose_browser(lambda _: '99')
        self.assertFalse((self.session.directory/'browser.json').exists())
        host.write_json(self.session.directory/'browser.json',{'browser':'edge'})
        with redirect_stdout(io.StringIO()):self.session.choose_browser(lambda _: '1')
        self.assertEqual(self.session.browser_preference(),'default')
    def test_browser_path_is_quoted_without_interpreting_apostrophes(self):
        host.write_json(self.session.directory/'browser.json',{'browser':'chrome'})
        self.session.console_origin='http://172.25.1.2:8088'
        with patch.object(self.session,'browser_executable',return_value=r"C:\Users\user\Browser's Folder\chrome.exe"),patch.object(host,'windows_script') as script:
            self.session.open_browser()
        self.assertIn("-FilePath 'C:\\Users\\user\\Browser''s Folder\\chrome.exe'",script.call_args.args[0])
    def test_menu_browser_choice_does_not_add_an_open_prompt_or_duplicate_menu(self):
        answers=iter(['6','3'])
        def read(_):
            try:return next(answers)
            except StopIteration:raise EOFError()
        with patch.object(self.session,'browser_executable',return_value=r'C:\Edge\msedge.exe'),redirect_stdout(io.StringIO()) as output:
            self.session.console_menu(read)
        self.assertEqual(self.session.browser_preference(),'edge')
        self.assertEqual(output.getvalue().count('1  Open browser'),1)
    def test_shutdown_confirmation_and_duplicate_do_not_mutate(self):
        self.session.preflight=Mock()
        with self.assertRaisesRegex(ValueError,'Confirm'):self.session.request({'action':'shutdown'})
        self.session.busy=True
        with self.assertRaisesRegex(ValueError,'already'):self.session.request({'action':'shutdown','confirmation':'SHUT DOWN HOST'})
        self.session.preflight.assert_not_called()
    def test_other_distribution_does_not_block_owned_host_shutdown(self):
        self.session.manager=Mock(return_value=self.state)
        self.session.containers=Mock(return_value=[])
        with patch.object(host,'running_distros',return_value=['Ubuntu','Other']):
            self.assertEqual(self.session.preflight(),self.state)
    def test_network_restart_rejects_other_distribution_before_stopping_games(self):
        (self.session.directory/'lan-settings.json').write_text('{}')
        self.session.manager=Mock()
        with patch.object(host,'running_distros',return_value=['Ubuntu','Other']):
            with self.assertRaisesRegex(ValueError,'Close other'):self.session.preflight()
        self.session.manager.assert_not_called()
    def test_saved_network_configuration_uses_global_shutdown_only_when_alone(self):
        (self.session.directory/'lan-settings.json').write_text('{}')
        events=self.sequence()
        self.assertEqual(events[-1],[host.WSL,'--shutdown'])
    def test_new_distribution_prevents_global_shutdown(self):
        (self.session.directory/'lan-settings.json').write_text('{}')
        self.session.manager=Mock(return_value={'operation':{'id':'op','phase':'completed'},'projectId':'world','services':[]})
        self.session.containers=lambda:[];self.session.select_owned=lambda *_:[]
        with patch.object(host,'running_distros',return_value=['Ubuntu','Other']),patch.object(host.time,'sleep'),patch.object(host,'run') as command:
            self.session.shutdown(self.state)
        command.assert_not_called()
        self.assertEqual(self.session.phase,'failed')
    def test_private_reconciliation_preserves_resume_intent(self):
        (self.session.directory/'lan-settings.json').write_text(json.dumps({'mode':'bridged'}))
        host.write_json(self.session.directory/'resume.json',{'world':'world','resume':True,'stopOperation':'old'})
        self.session.network_info=Mock(return_value={'networkingMode':'bridged','dockerIp':'192.168.23.220'})
        self.session.manager=Mock(side_effect=[{'profile':{'address':'172.25.1.2'}},{'operation':{'id':'new'}},{'operation':{'id':'new','phase':'completed'}}])
        self.session.reconcile_private_address()
        self.session.manager.assert_any_call('network.set',mode='private',address='192.168.23.220',expectedAddress='172.25.1.2')
        self.assertEqual(json.loads((self.session.directory/'resume.json').read_text()),{'world':'world','resume':True,'stopOperation':'new'})
    def test_public_address_is_preserved_when_host_lan_changes(self):
        (self.session.directory/'lan-settings.json').write_text(json.dumps({'mode':'bridged'}))
        self.session.network_info=Mock(return_value={'networkingMode':'bridged','dockerIp':'192.168.23.220'})
        self.session.manager=Mock(return_value={'profile':{'address':'8.8.8.8'}})
        self.session.reconcile_private_address()
        self.session.manager.assert_called_once_with('status')
    def test_foreign_workload_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Another Docker'):self.session.select_owned([{'Id':'foreign','Config':{'Labels':{}}}],'world')
    def test_only_owned_installation_world_and_settings_are_selected(self):
        rows=[{'Id':'app','Config':{'Labels':{'com.docker.compose.project':'fixture'}}},{'Id':'db','Config':{'Labels':{'io.dst.managed':'true','io.dst.project':'world'}}},{'Id':'settings','Config':{'Labels':{'io.dst.managed':'true','io.dst.component':'settings','io.dst.project':'old'}}}]
        self.assertEqual(self.session.select_owned(rows,'world'),['app','db','settings'])
    def test_backup_and_operation_block_shutdown(self):
        for extra in ({'operation':{'phase':'running'}},{'backups':[{'phase':'running'}]}):
            self.session.manager=Mock(return_value={**self.state,**extra})
            with patch.object(host,'running_distros',return_value=['Ubuntu']):
                with self.assertRaises(ValueError):self.session.preflight()

    def test_fresh_install_without_a_prior_operation_can_check_host_shutdown(self):
        self.session.manager=Mock(return_value={**self.state,'operation':None})
        self.session.containers=Mock(return_value=[])
        with patch.object(host,'running_distros',return_value=['Ubuntu']):
            self.assertIsNone(self.session.preflight()['operation'])
    def sequence(self,stop_phase='completed',maps=None):
        events=[]
        def manager(action):
            events.append(action)
            return {'operation':{'id':'operation','phase':stop_phase},'projectId':'world','services':maps or []}
        self.session.manager=manager
        self.session.containers=lambda:[]
        self.session.select_owned=lambda *_:['app','db']
        self.session.docker=lambda *args,**kwargs:events.append(list(args))
        with patch.object(host,'running_distros',return_value=['Ubuntu']),patch.object(host.time,'sleep'),patch.object(host,'run',side_effect=lambda args,**kwargs:events.append(args)):
            self.session.shutdown(self.state)
        return events
    def test_battlegroup_finishes_before_container_stop_and_wsl_shutdown(self):
        events=self.sequence()
        self.assertEqual(events,['services.stop','status',['stop','--time','120','app','db'],[host.WSL,'--terminate','Ubuntu']])
        resume=json.loads((self.root/'host-session/resume.json').read_text());self.assertTrue(resume['resume']);self.assertEqual(resume['world'],'world')
    def test_other_distribution_is_not_terminated(self):
        self.session.manager=Mock(return_value={'operation':{'id':'op','phase':'completed'},'projectId':'world','services':[]})
        self.session.containers=lambda:[];self.session.select_owned=lambda *_:['app']
        self.session.docker=Mock()
        with patch.object(host,'running_distros',side_effect=[['Ubuntu'],['Ubuntu','Other']]),patch.object(host.time,'sleep'),patch.object(host,'run') as command:
            self.session.shutdown(self.state)
        command.assert_called_once_with([host.WSL,'--terminate','Ubuntu'],timeout=60)

    def test_failed_bg_stop_never_stops_containers_or_wsl(self):
        events=self.sequence(stop_phase='failed')
        self.assertEqual(events,['services.stop','status']);self.assertEqual(self.session.phase,'failed');self.assertFalse(self.session.busy)
    def test_live_game_blocks_host_shutdown_even_after_operation_completion(self):
        events=self.sequence(maps=[{'component':'game-1','state':'running'}])
        self.assertEqual(events,['services.stop','status']);self.assertEqual(self.session.phase,'failed')
    def test_start_opens_interface_address_and_owns_only_one_session(self):
        self.session.prepare_backup_mirror=Mock()
        self.session.compose=Mock();self.session.app_id=Mock(return_value='app')
        def docker(*args,**kwargs):
            if args[0]=='inspect':return json.dumps([{'State':{'Health':{'Status':'healthy'}}}])
            return 'http://127.0.0.1:8088/?t=synthetic-only'
        self.session.docker=docker;self.session.serve=Mock()
        with patch.object(host,'run',return_value=Mock(stdout=b'172.25.1.2 172.17.0.1')),patch.object(host,'windows_script') as script:
            self.session.start()
        self.assertTrue(script.call_args.args[0].startswith("Start-Process 'http://172.25.1.2:8088/?_dst_launch="))
        self.assertNotIn('synthetic-only',script.call_args.args[0])
        self.session.compose.assert_called_once_with('up','-d','--no-build')
        other=host.HostSession(self.root);other.compose=Mock()
        other.reopen_existing=Mock()
        other.start()
        other.reopen_existing.assert_called_once_with(True)
        other.compose.assert_not_called()
        self.session.session_lock.close();other.session_lock.close()

    def test_unknown_request_cannot_execute_a_command(self):
        with self.assertRaises(ValueError):self.session.request({'action':'exec','command':'arbitrary'})

    def test_loopback_read_never_starts_a_route_change(self):
        with patch.object(host,'windows_script',return_value='{"publicIp":"8.8.4.4","target":"192.168.23.219","multiple":false}'),patch.object(host.threading,'Thread') as thread:
            value=self.session.request({'action':'loopback.get','publicIp':'8.8.4.4'})
        self.assertEqual(value['target'],'192.168.23.219');thread.assert_not_called()

    def test_loopback_change_requires_confirmation_before_reading_windows(self):
        with patch.object(host,'windows_script') as windows:
            with self.assertRaisesRegex(ValueError,'Confirm'):self.session.request({'action':'loopback.set','publicIp':'8.8.4.4','target':'192.168.23.106','expectedTarget':'192.168.23.219'})
        windows.assert_not_called()

    def test_loopback_stale_or_identical_target_never_starts_elevation(self):
        request={'action':'loopback.set','publicIp':'8.8.4.4','target':'192.168.23.106','expectedTarget':'192.168.23.219','confirmation':'CHANGE LOOPBACK TARGET'}
        with patch.object(host,'windows_script',return_value='{"publicIp":"8.8.4.4","target":"192.168.23.218","multiple":false}'),patch.object(host.threading,'Thread') as thread:
            with self.assertRaisesRegex(ValueError,'changed'):self.session.request(request)
            self.session.request({**request,'expectedTarget':'192.168.23.218','target':'192.168.23.218'})
        thread.assert_not_called()

    def test_failed_loopback_elevation_records_error_without_restarting_games(self):
        operation={'id':'route','phase':'running'}
        self.session.manager=Mock()
        with patch('wsl_loopback.apply',side_effect=ValueError('Windows approval cancelled')):
            self.session.change_loopback({'publicIp':'8.8.4.4','target':'192.168.23.106'},operation)
        result=json.loads((self.session.directory/'loopback-operation.json').read_text())
        self.assertEqual(result['phase'],'failed');self.assertEqual(result['error'],'Windows approval cancelled')
        self.session.manager.assert_not_called();self.assertFalse(self.session.busy)

    def test_owner_recovery_lists_then_resets_exact_owner_after_confirmation(self):
        self.session.compose=Mock(side_effect=['Enabled\tOwner With Spaces','One-time password: synthetic-only'])
        with redirect_stdout(io.StringIO()) as output:
            self.session.owner_recovery(lambda _: 'RESET OWNER')
        args=self.session.compose.call_args.args
        self.assertIn('Owner With Spaces',args)
        self.assertEqual(args[-2:],('-Confirmation','RESET OWNER'))
        self.assertIn('One-time password:',output.getvalue())
        self.assertFalse(self.session.busy);self.assertEqual(self.session.phase,'ready')

    def test_missing_owner_recovery_displays_current_setup_link_without_resetting_accounts(self):
        self.session.console_origin='http://172.25.1.2:8088'
        self.session.compose=Mock(side_effect=['','http://127.0.0.1:8088/?t=synthetic-only'])
        with redirect_stdout(io.StringIO()) as output,patch.object(host,'windows_script') as windows:
            self.session.owner_recovery()
        self.assertIn('Create your first Owner account:',output.getvalue())
        self.assertIn('http://172.25.1.2:8088/?t=synthetic-only',output.getvalue())
        self.assertNotIn('printed by the installer',output.getvalue())
        self.assertEqual(self.session.compose.call_count,2)
        self.assertFalse(any('Reset' in call.args for call in self.session.compose.call_args_list))
        windows.assert_not_called()
        self.assertFalse(self.session.busy)

    def test_first_browser_launch_displays_owner_link_without_an_unauthenticated_browser_dead_end(self):
        self.session.owner_setup_required.return_value=True
        self.session.console_origin='https://192.168.1.5:8443'
        self.session.compose=Mock(return_value='http://127.0.0.1:18088/?t=synthetic-only')
        with redirect_stdout(io.StringIO()) as output,patch.object(host,'windows_script') as windows:
            self.session.open_browser()
        self.assertIn('https://192.168.1.5:8443/?t=synthetic-only',output.getvalue())
        windows.assert_not_called()

    def test_cancelled_owner_recovery_never_resets_an_account(self):
        self.session.compose=Mock(return_value='Enabled\tFirstOwner\nEnabled\tSecondOwner')
        with redirect_stdout(io.StringIO()):self.session.owner_recovery(lambda _: '')
        self.session.compose.assert_called_once()
        self.assertFalse(self.session.busy)

    def test_console_menu_accepts_recovery_selection(self):
        answers=iter(['2'])
        def read(_):
            try:return next(answers)
            except StopIteration:raise EOFError()
        self.session.owner_recovery=Mock()
        with redirect_stdout(io.StringIO()) as output:self.session.console_menu(read)
        self.session.owner_recovery.assert_called_once_with(read)
        self.assertIn('Create Owner account / recover password',output.getvalue())

    def test_console_shutdown_runs_from_menu_selection_without_another_prompt(self):
        answers=iter(['5'])
        prompts=[]
        def read(prompt):
            prompts.append(prompt)
            try:return next(answers)
            except StopIteration:raise EOFError()
        self.session.request=Mock()
        with redirect_stdout(io.StringIO()):self.session.console_menu(read)
        self.session.request.assert_called_once_with({'action':'shutdown','confirmation':'SHUT DOWN HOST'})
        self.assertEqual(prompts,['Choose an option: '])

    def test_console_shutdown_shows_progress_until_failure_then_allows_retry(self):
        requested=host.threading.Event();second_prompt=host.threading.Event();prompts=[]
        def read(prompt):
            prompts.append(prompt)
            if len(prompts)==1:return '5'
            second_prompt.set();raise EOFError()
        def request(_):
            self.session.phase='stopping';self.session.shutdown_finished.clear();requested.set()
        self.session.request=Mock(side_effect=request)
        thread=host.threading.Thread(target=self.session.console_menu,args=(read,))
        with redirect_stdout(io.StringIO()) as output:
            thread.start()
            try:
                self.assertTrue(requested.wait(1))
                self.assertFalse(second_prompt.wait(.03))
                self.session.progress('failed','Host shutdown failed.')
            finally:
                self.session.shutdown_finished.set();thread.join(1)
        self.assertFalse(thread.is_alive())
        text=output.getvalue()
        self.assertEqual(text.count('5  Shut down host'),1)
        self.assertTrue(second_prompt.is_set())

    def test_browser_open_finishes_before_next_prompt_and_menu_is_not_duplicated(self):
        started=host.threading.Event();release=host.threading.Event();prompts=[]
        def read(prompt):
            prompts.append(prompt)
            if len(prompts)==1:return '1'
            self.assertTrue(release.is_set());raise EOFError()
        def open_console(_):
            started.set();release.wait(1)
        self.session.start_console=open_console
        thread=host.threading.Thread(target=self.session.console_menu,args=(read,))
        with redirect_stdout(io.StringIO()) as output:
            thread.start()
            try:
                self.assertTrue(started.wait(1));self.assertEqual(len(prompts),1)
            finally:release.set();thread.join(1)
        self.assertEqual(len(prompts),2)
        self.assertEqual(output.getvalue().count('1  Open browser'),1)
        self.assertIn('DST console is available.',output.getvalue())

    def test_container_cannot_reopen_the_host(self):
        with self.assertRaisesRegex(ValueError,'desktop icon'):
            self.session.request({'action':'open','browser':True},peer_uid=10001)
        self.assertFalse(self.session.busy)

    def test_busy_host_rejects_desktop_reopen(self):
        self.session.busy=True
        with self.assertRaisesRegex(ValueError,'still running'):
            self.session.request({'action':'open','browser':True},peer_uid=0)

    def test_failed_reopen_reports_failure_and_allows_retry(self):
        self.session.start_console=Mock(side_effect=ValueError('Docker startup failed'))
        self.session.busy=True
        self.session.recover_console(False)
        self.assertEqual(self.session.phase,'failed');self.assertFalse(self.session.busy)
        self.session.start_console=Mock()
        self.session.recover_console(False)
        self.assertEqual(self.session.phase,'ready')

    def test_failed_world_start_retains_resume_intent(self):
        path=self.root/'host-session/resume.json'
        path.write_text(json.dumps({'resume':True,'world':'world','startOperation':'start'}))
        self.session.manager=Mock(return_value={'desiredState':'running','operation':{'id':'start','phase':'failed'}})
        self.session.finish_resume()
        self.assertTrue(path.exists());self.assertEqual(self.session.phase,'failed')

    def test_confirmed_world_start_clears_resume_intent(self):
        path=self.root/'host-session/resume.json'
        path.write_text(json.dumps({'resume':True,'world':'world','startOperation':'start'}))
        self.session.manager=Mock(return_value={'desiredState':'running','operation':{'id':'start','phase':'completed'}})
        self.session.finish_resume()
        self.assertFalse(path.exists())

    def test_each_browser_launch_bypasses_old_cached_root_redirect(self):
        self.session.console_origin='http://172.25.1.2:8088'
        first=self.session.browser_url();second=self.session.browser_url()
        self.assertTrue(first.startswith('http://172.25.1.2:8088/?_dst_launch='))
        self.assertNotEqual(first,second)

    def test_disabled_https_override_is_not_reapplied_by_the_host_window(self):
        config=self.session.config;config['composeFiles'].append(str(self.root/'https.compose.json'))
        (self.root/'host-session/config.json').write_text(json.dumps(config))
        self.ready_console()
        with patch.object(host,'run',return_value=Mock(stdout=b'172.25.1.2')):
            self.session.start_console(False)
        self.assertNotIn(str(self.root/'https.compose.json'),self.session.config['composeFiles'])
        self.assertEqual(self.session.console_origin,'http://172.25.1.2:8088')

    def test_https_enabled_after_launch_is_used_on_the_next_open(self):
        (self.root/'https.compose.json').write_text(json.dumps({'x-dst-https-origin':'https://172.25.1.2:8443'}))
        self.ready_console()
        with patch.object(host,'run',return_value=Mock(stdout=b'172.25.1.2')):
            self.session.start_console(False)
        self.assertIn(str(self.root/'https.compose.json'),self.session.config['composeFiles'])
        self.assertEqual(self.session.console_origin,'https://172.25.1.2:8443')

    def test_desktop_start_prepares_and_retains_mirror_without_enabling_copying(self):
        import mirror_config
        folder=self.root/'backup-copies'
        self.session.compose=Mock(return_value=json.dumps({'services':{'manager':{'volumes':[]}}}))
        with patch.dict(host.os.environ,{'DST_BACKUP_MIRROR_DIR':str(folder)}):
            self.session.prepare_backup_mirror()
        override=self.root/'mirror.compose.json'
        self.assertIn(str(override),self.session.config['composeFiles'])
        saved=json.loads((self.root/'host-session/config.json').read_text())
        self.assertIn(str(override),saved['composeFiles'])
        self.assertEqual(json.loads((folder/mirror_config.MARKER).read_text())['composeProject'],'fixture')
        canary=folder/'existing-copy';canary.write_text('preserve')
        before=override.read_bytes()
        with patch.dict(host.os.environ,{'DST_BACKUP_MIRROR_DIR':str(self.root/'different')}):
            self.session.prepare_backup_mirror()
        self.assertEqual(override.read_bytes(),before);self.assertEqual(canary.read_text(),'preserve')
        self.assertEqual(self.session.config['composeFiles'].count(str(override)),1)
        self.assertNotIn('backupMirror',saved)
    def test_existing_custom_mirror_mount_is_preserved(self):
        self.session.compose=Mock(return_value=json.dumps({'services':{'manager':{'volumes':[{'type':'bind','source':'/custom/copies','target':'/mirror'}]}}}))
        self.session.prepare_backup_mirror()
        self.assertFalse((self.root/'mirror.compose.json').exists())
        self.assertEqual(self.session.config['composeFiles'],['/home/test/current/compose.yaml'])
    def ready_console(self):
        self.session.prepare_backup_mirror=Mock()
        self.session.compose=Mock();self.session.app_id=Mock(return_value='app')
        self.session.docker=lambda *args,**kwargs:json.dumps([{'State':{'Health':{'Status':'healthy'}}}]) if args[0]=='inspect' else 'http://127.0.0.1:8088/'

    def test_http_console_prefers_windows_loopback_when_wsl_interface_is_blocked(self):
        self.ready_console();self.session.windows_console_reachable=Mock(return_value=True)
        self.session.open_browser=Mock()
        with patch.object(host,'run',return_value=Mock(stdout=b'172.25.1.2')):
            self.session.start_console(True)
        self.assertEqual(self.session.console_origin,'http://127.0.0.1:8088')
        self.session.windows_console_reachable.assert_called_once_with('http://127.0.0.1:8088')
        self.session.open_browser.assert_called_once()

    def test_unreachable_windows_console_never_reports_available_or_opens_a_dead_url(self):
        self.ready_console();self.session.windows_console_reachable=Mock(return_value=False)
        self.session.open_browser=Mock()
        with patch.object(host,'run',return_value=Mock(stdout=b'172.25.1.2')),redirect_stdout(io.StringIO()):
            self.session.recover_console(True)
        self.assertEqual(self.session.phase,'failed')
        self.assertIn('Windows cannot reach',self.session.message)
        self.session.open_browser.assert_not_called()

    def test_windows_console_probe_checks_http_without_proxy_or_redirect_and_has_a_timeout(self):
        with patch.object(host,'windows_script',return_value='ready') as script:
            self.assertTrue(host.HostSession.windows_console_reachable(self.session,'http://127.0.0.1:8088'))
        command=script.call_args.args[0]
        self.assertIn('$request.Proxy=$null',command)
        self.assertIn('$request.Timeout=3000',command)
        self.assertIn('$request.AllowAutoRedirect=$false',command)

    def test_accepted_world_start_keeps_resume_until_completion(self):
        self.ready_console();path=self.root/'host-session/resume.json'
        path.write_text(json.dumps({'world':'world','resume':True,'stopOperation':'stop'}))
        self.session.manager=Mock(side_effect=[{'projectId':'world','desiredState':'stopped','operation':{'id':'stop'}},{'operation':{'id':'start','phase':'running'}}])
        with patch.object(host,'run',return_value=Mock(stdout=b'172.25.1.2')),patch.object(host.threading,'Thread'):
            self.session.start_console(False)
        self.assertEqual(json.loads(path.read_text())['startOperation'],'start')
        self.session.manager.assert_any_call('services.start')

    def test_deliberate_later_stop_supersedes_saved_host_resume(self):
        self.ready_console();path=self.root/'host-session/resume.json'
        path.write_text(json.dumps({'world':'world','resume':True,'stopOperation':'old-stop'}))
        self.session.manager=Mock(return_value={'projectId':'world','desiredState':'stopped','operation':{'id':'deliberate-later-stop'}})
        with patch.object(host,'run',return_value=Mock(stdout=b'172.25.1.2')):
            self.session.start_console(False)
        self.assertFalse(path.exists());self.session.manager.assert_called_once_with('status')

    def test_second_desktop_launch_recovers_existing_session_over_real_socket(self):
        marker=self.root/'reopened'
        def serve():
            session=host.HostSession(self.root)
            session.start_console=lambda browser:marker.write_text(str(browser))
            session.serve()
        process=multiprocessing.get_context('fork').Process(target=serve,daemon=True)
        process.start()
        try:
            deadline=time.monotonic()+5
            while not (self.root/'host-session/host.sock').exists() and time.monotonic()<deadline:time.sleep(.01)
            self.session.start(open_browser=False)
            while time.monotonic()<deadline:
                if marker.exists() and marker.read_text()=='False':break
                time.sleep(.01)
            self.assertEqual(marker.read_text(),'False')
            self.assertTrue(process.is_alive())
        finally:
            process.terminate();process.join(timeout=5)

    def test_disconnected_client_cannot_end_the_foreground_host(self):
        path=str(self.root/'host-session/host.sock')
        def serve():
            session=host.HostSession(self.root)
            original=session.request
            def delayed(request,peer_uid=None):
                time.sleep(.05)
                return original(request,peer_uid)
            session.request=delayed;session.serve()
        process=multiprocessing.get_context('fork').Process(target=serve,daemon=True)
        process.start()
        try:
            deadline=time.monotonic()+5
            while not Path(path).exists() and time.monotonic()<deadline:time.sleep(.01)
            with socket.socket(socket.AF_UNIX) as connection:
                connection.connect(path);connection.sendall(b'{"action":"status"}\n')
            time.sleep(.1)
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(2);connection.connect(path);connection.sendall(b'{"action":"status"}\n')
                self.assertTrue(json.loads(connection.recv(65536))['ok'])
            self.assertTrue(process.is_alive())
        finally:
            process.terminate();process.join(timeout=5)
    def test_shortcut_uses_foreground_host_and_current_windows_desktop_without_tokens(self):
        with patch.object(host,'run',return_value=Mock(stdout=b'\\\\wsl.localhost\\Ubuntu\\home\\test\\current\\app\\assets\\icon.ico')),patch.object(host,'windows_script',return_value='shortcut') as script:
            self.assertEqual(self.session.shortcut(),'shortcut')
        command=script.call_args.args[0]
        self.assertIn("GetFolderPath('Desktop')",command)
        self.assertIn('host_session.py',command);self.assertIn('desktop',command)
        self.assertIn('-u root',command);self.assertNotIn('?t=',command)
        self.assertIn('different DST Docker shortcut',command)

if __name__=='__main__':unittest.main()
