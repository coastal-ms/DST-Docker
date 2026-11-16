import json
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import Mock,patch
from https_control import HttpsControl
import portal_update


class HttpsControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'portal-update').mkdir()
        self.compose=Mock(return_value=b'{"name":"dst"}')
        self.control=HttpsControl(self.root,lambda:self.root,self.compose)
        self.control.reconcile_tailscale=Mock()
        self.control.addresses=Mock(return_value=['192.0.2.1'])
        self.control.certificate=Mock(return_value={'pem':'public certificate fixture','sha256':'a'*64})
    def tearDown(self):self.temp.cleanup()
    def pending(self):
        (self.root/'https.pending.compose.json').write_text(json.dumps({'x-dst-https-origin':'https://192.0.2.1:8088','x-dst-http-internal-port':18088}))
    def test_preparation_does_not_start_services_or_replace_the_http_listener(self):
        tls=Mock();self.control.tls=Mock(return_value=tls)
        with patch('threading.Thread') as thread:
            result=self.control.start({'action':'https.prepare','address':'192.0.2.1','port':8088})
            self.assertEqual(result['operation']['phase'],'running');thread.return_value.start.assert_called_once()
        self.control.prepare({'address':'192.0.2.1','port':8088})
        tls.prepare.assert_called_once();tls.initialize_root.assert_called_once_with('dst')
        self.assertFalse((self.root/'https.compose.json').exists());self.compose.assert_called_with('config','--format','json')
    def test_host_addresses_ports_and_arbitrary_arguments_are_rejected_before_work(self):
        cases=[{'action':'https.prepare','address':'198.51.100.10','port':8088},
               {'action':'https.prepare','address':'192.0.2.1;id','port':8088},
               {'action':'https.prepare','address':'192.0.2.1','port':True},
               {'action':'https.prepare','address':'192.0.2.1','port':8088,'command':'id'},
               {'action':'https.disable','port':8088,'path':'/outside'}]
        with patch('threading.Thread') as thread:
            for request in cases:
                with self.assertRaises(ValueError):self.control.start(request)
            thread.assert_not_called()
    def test_enabling_requires_the_exact_prepared_certificate_and_current_address(self):
        self.pending()
        with patch('threading.Thread') as thread:
            with self.assertRaisesRegex(ValueError,'certificate changed'):self.control.start({'action':'https.enable','sha256':'b'*64,'port':8088})
            self.control.addresses.return_value=['192.0.2.2']
            with self.assertRaisesRegex(ValueError,'address changed'):self.control.start({'action':'https.enable','sha256':'a'*64,'port':8088})
            self.assertFalse((self.root/'https.compose.json').exists());thread.assert_not_called()
    def test_enabling_and_disabling_only_use_the_fixed_console_launcher(self):
        self.pending();self.control.launch=Mock()
        self.control.worker({'action':'https.enable','address':'192.0.2.1','port':8088})
        self.control.launch.assert_called_once_with('https','192.0.2.1','8088')
        self.assertTrue((self.root/'https.compose.json').exists())
        self.assertEqual(self.control.operation['phase'],'completed')
        self.control.worker({'action':'https.disable','port':8088})
        self.control.launch.assert_called_with('http','8088')
        self.assertTrue((self.root/'https.saved.compose.json').exists())
    def test_failed_enable_attempts_http_recovery_without_reporting_success(self):
        self.pending();self.control.launch=Mock(side_effect=[ValueError('fixture'),None])
        self.control.worker({'action':'https.enable','address':'192.0.2.1','port':8088})
        self.assertEqual(self.control.launch.call_args.args,('http','8088'))
        self.assertEqual(self.control.operation['phase'],'failed')
        self.assertTrue((self.root/'https.pending.compose.json').exists())
    def test_restarted_host_marks_unfinished_setup_failed_and_keeps_evidence(self):
        self.pending();self.control.record(id='fixture',phase='running')
        restored=HttpsControl(self.root,lambda:self.root,self.compose)
        self.assertEqual(restored.operation['phase'],'failed');self.assertTrue((self.root/'https.pending.compose.json').exists())
    def test_status_contains_no_proxy_credentials_or_private_key(self):
        self.pending();self.control.certificate_cache={'pem':'public fixture','sha256':'a'*64}
        status=self.control.status(8088)
        self.assertFalse(status['enabled']);self.assertTrue(status['prepared'])
        self.assertEqual(status['sha256'],'a'*64);self.assertNotIn('pem',status)
        self.assertFalse(status['clientTrustInstalled'])
    def test_update_and_https_jobs_cannot_overlap(self):
        updater=portal_update.Updater(self.root);updater.https=self.control
        self.control.operation={'phase':'running'}
        with self.assertRaisesRegex(ValueError,'Wait for HTTPS'):updater.install({'action':'install','tag':'v1.0.18','commit':'a'*40,'confirmation':'UPDATE DST DOCKER'})
        updater.operation={'phase':'running'}
        self.control.operation=None
        with self.assertRaisesRegex(ValueError,'Docker update'):updater.request({'action':'https.prepare','address':'192.0.2.1','port':8088})
    def test_unknown_actions_cannot_reach_the_launcher(self):
        updater=portal_update.Updater(self.root);updater.https=self.control
        with self.assertRaises(ValueError):updater.request({'action':'https.exec','port':8088,'command':'id'})


    def test_existing_tailscale_mode_is_reconciled_to_the_new_listener(self):
        self.compose.return_value=b'{"ok":true,"data":{"mode":"private"}}'
        HttpsControl.reconcile_tailscale(self.control,18088)
        request=json.loads(self.compose.call_args.kwargs['input'])
        self.assertEqual(request,{'action':'tailscale.get','port':18088})
        self.assertEqual(self.compose.call_args.args[:4],('exec','-T','dst','python3'))
    def test_bridge_addresses_are_not_offered_for_browser_setup(self):
        rows=[{'ifname':'eth0','addr_info':[{'family':'inet','local':'192.0.2.1'}]},
              {'ifname':'docker0','addr_info':[{'family':'inet','local':'172.17.0.1'}]},
              {'ifname':'br-fixture','addr_info':[{'family':'inet','local':'172.18.0.1'}]},
              {'ifname':'lo','addr_info':[{'family':'inet','local':'127.0.0.1'}]}]
        with patch('subprocess.check_output',return_value=json.dumps(rows).encode()):
            self.assertEqual(HttpsControl.addresses(self.control),['192.0.2.1'])

if __name__=='__main__':unittest.main()
