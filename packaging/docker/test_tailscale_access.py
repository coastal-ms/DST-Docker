import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import tailscale_access as access


class TailscaleAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.path=self.root/'tailscale.json';self.origin=self.root/'origin.json'
        self.engine=Mock(spec=['request','assert_owned','lifecycle','exec_internal']);self.project='a'*32
        self.node={'Id':'owned','State':{'Status':'running'}}
    def tearDown(self):self.temp.cleanup()
    def test_verified_private_and_public_configuration_persist_only_the_owned_url(self):
        for mode in ('private','public'):
            config={'Web':{'dst-console.tail123.ts.net:443':{'Handlers':{'/':{'Proxy':'http://127.0.0.1:8088'}}}},'AllowFunnel':{'dst-console.tail123.ts.net:443':mode=='public'}}
            with patch.object(access,'owned',return_value=self.node),patch.object(access,'ensure_container',return_value='owned'),patch.object(access,'command_output',return_value=''),patch.object(access,'cli',side_effect=[json.dumps({'BackendState':'Running','Self':{'DNSName':'dst-console.tail123.ts.net.'}}),'',json.dumps(config)]) as cli:
                access.change(self.engine,self.project,self.path,self.origin,mode,8088)
            self.assertEqual(access.read(self.path)['phase'],'connected')
            self.assertEqual(access.read(self.origin),{'origin':'https://dst-console.tail123.ts.net','mode':mode})
            self.assertEqual(cli.call_args_list[1].args[-1],['serve','reset'])
        self.engine.lifecycle.assert_not_called()
    def test_missing_funnel_permission_is_not_reported_connected(self):
        self.origin.write_text('{}')
        with patch.object(access,'owned',return_value=self.node),patch.object(access,'ensure_container',return_value='owned'),patch.object(access,'command_output',return_value='https://login.tailscale.com/f/funnel'),patch.object(access,'cli',side_effect=[json.dumps({'BackendState':'Running','Self':{'DNSName':'dst-console.tail123.ts.net.'}}),'','{}']):
            access.change(self.engine,self.project,self.path,self.origin,'public',8088)
        value=access.read(self.path)
        self.assertEqual(value['phase'],'setup-required');self.assertTrue(value['loginUrl'])
        self.assertFalse(self.origin.exists())
    def test_off_stops_only_the_owned_proxy_and_keeps_credentials(self):
        self.origin.write_text('{}')
        with patch.object(access,'owned',return_value=self.node):access.change(self.engine,self.project,self.path,self.origin,'off',8088)
        self.engine.lifecycle.assert_called_once_with('owned',self.project,'stop')
        self.engine.request.assert_not_called();self.assertFalse(self.origin.exists())
        self.assertEqual(access.read(self.path)['phase'],'off')
    def test_enrollment_links_and_node_details_are_absent_from_read_only_map_link(self):
        access.write(self.root/'tailscale.json',{'mode':'private','phase':'connected','url':'https://dst-console.tail123.ts.net','loginUrl':'https://login.tailscale.com/a/secret'})
        result=access.request(self.engine,self.project,self.root,self.root,'link')
        self.assertEqual(result,{'url':'https://dst-console.tail123.ts.net','mode':'private'})
        self.engine.request.assert_not_called()
    def test_foreign_node_cannot_be_adopted_or_stopped(self):
        self.engine.request.return_value=self.node
        self.engine.assert_owned.side_effect=ValueError('Foreign container')
        with self.assertRaisesRegex(ValueError,'Foreign'):access.owned(self.engine,self.project)
        self.engine.lifecycle.assert_not_called()
    def test_requests_cannot_supply_an_arbitrary_command_or_forwarding_target(self):
        for mode,port in [('exec',8088),('private',22),('public',True)]:
            with self.assertRaises(ValueError):access.request(self.engine,self.project,self.root,self.root,'set',mode,port)
        self.engine.exec_internal.assert_not_called()
    def test_untrusted_names_and_enrollment_urls_are_rejected(self):
        for name in ['evil.example','dst.tail.ts.net/evil','dst.tail.ts.net:443','https://dst.tail.ts.net']:
            self.assertEqual(access.connected_url({'Self':{'DNSName':name}}),'')
        self.assertEqual(access.login_url('https://login.tailscale.com.evil.example/a/1'),'')

    def test_manager_restart_resumes_enabled_access_with_its_saved_listener_port(self):
        access.write(self.root/'tailscale.json',{'mode':'private','phase':'connected','port':18088})
        with patch.object(access,'request') as request:
            access.resume(self.engine,self.project,self.root,self.root)
            request.assert_called_once_with(self.engine,self.project,self.root,self.root,'set','private',18088)
        access.write(self.root/'tailscale.json',{'mode':'off','phase':'off'})
        with patch.object(access,'request') as request:
            access.resume(self.engine,self.project,self.root,self.root)
            request.assert_not_called()


if __name__=='__main__':unittest.main()
