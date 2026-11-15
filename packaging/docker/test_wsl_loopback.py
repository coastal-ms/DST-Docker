import json
import unittest
from unittest.mock import Mock
import wsl_loopback as loopback


class LoopbackTests(unittest.TestCase):
    def test_read_only_snapshot_only_reads_the_exact_host_route(self):
        windows=Mock(return_value=json.dumps({'target':'192.168.23.219','publicIp':'8.8.4.4','multiple':False}))
        result=loopback.snapshot(windows,'8.8.4.4')
        self.assertEqual(result['target'],'192.168.23.219')
        script=windows.call_args.args[0]
        self.assertIn("DestinationPrefix '8.8.4.4/32'",script)
        self.assertNotIn('New-NetRoute',script);self.assertNotIn('Remove-NetRoute',script)

    def test_invalid_inputs_never_reach_windows(self):
        for value in ('bad','192.168.23.23','127.0.0.1','224.1.2.3',"8.8.4.4';bad"):
            windows=Mock()
            with self.subTest(value=value),self.assertRaises(ValueError):loopback.snapshot(windows,value)
            windows.assert_not_called()
        for target in ('8.8.8.8','127.0.0.1','bad',"192.168.23.106';bad"):
            with self.subTest(target=target),self.assertRaises(ValueError):loopback.validate({'publicIp':'8.8.4.4','target':target,'expectedTarget':'192.168.23.219','confirmation':'CHANGE LOOPBACK TARGET'})

    def test_confirmation_and_current_target_are_required(self):
        change={'publicIp':'8.8.4.4','target':'192.168.23.106','expectedTarget':'192.168.23.219','confirmation':'CHANGE LOOPBACK TARGET'}
        for key in ('confirmation','target','expectedTarget'):
            value={k:v for k,v in change.items() if k!=key}
            with self.subTest(key=key),self.assertRaises(ValueError):loopback.validate(value)
        self.assertEqual(loopback.validate(change)['target'],'192.168.23.106')
        self.assertIsNone(loopback.validate({**change,'target':None})['target'])

    def test_elevation_failure_is_not_reported_as_success(self):
        change={'publicIp':'8.8.4.4','target':'192.168.23.106','expectedTarget':'192.168.23.219'}
        with self.assertRaisesRegex(ValueError,'cancelled'):loopback.apply(Mock(return_value='{"ok":false,"error":"Windows approval cancelled"}'),change)


if __name__=='__main__':unittest.main()
