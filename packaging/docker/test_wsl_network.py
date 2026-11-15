import json
import unittest
from unittest.mock import Mock,patch
import wsl_network


class WslNetworkTests(unittest.TestCase):
    def test_router_target_comes_from_windows_and_internal_address_stays_separate(self):
        windows=Mock(return_value=json.dumps({'dockerIp':'192.168.23.23'}))
        with patch.object(wsl_network,'local_address',return_value='172.25.199.100'):
            result=wsl_network.snapshot(windows,Mock(return_value=Mock(stdout=b'nat\n')))
        self.assertEqual(result['dockerIp'],'172.25.199.100')
        self.assertEqual(result['windowsIp'],'192.168.23.23')
        self.assertEqual(result['routerForwardIp'],'192.168.23.23')
        self.assertIn("DestinationPrefix '0.0.0.0/0'",windows.call_args.args[0])

    def test_unusable_windows_addresses_are_not_presented_as_router_targets(self):
        for address in ['127.0.0.1','169.254.1.1','0.0.0.0','bad']:
            with self.subTest(address=address):
                with self.assertRaises(ValueError):wsl_network.snapshot(Mock(return_value=json.dumps({'dockerIp':address})),Mock())


if __name__=='__main__':unittest.main()
