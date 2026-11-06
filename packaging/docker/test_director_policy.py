import json
import unittest
from unittest.mock import Mock,patch
from director_policy import apply


class PolicyTests(unittest.TestCase):
    def test_floor_preserves_other_live_overrides_and_checks_activation(self):
        requests=[]
        def open_url(request,timeout):
            requests.append(request)
            if isinstance(request,str):
                floor=1 if len(requests)>2 else 0
                body={'instancedMaps':{'SH_Arrakeen':{'cfg':{'minServers':floor},'webOverrideCfg':{'playerHardCap':42,'minServers':0}}}}
                data=json.dumps(body).encode()
            else:data=b''
            response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock();response.read.return_value=data
            return response
        with patch('director_policy.urllib.request.urlopen',side_effect=open_url):
            self.assertTrue(apply({'host':'dst-'+'a'*32+'-director','map':'SH_Arrakeen','floor':1})['applied'])
        body=json.loads(requests[1].data)
        self.assertEqual(body['ClassicalInstancingGroupConfig'],{'playerHardCap':42,'MinServers':1})
        self.assertEqual(body['MapName'],'SH_Arrakeen')

    def test_foreign_destinations_and_invalid_values_never_make_a_request(self):
        valid={'host':'dst-'+'a'*32+'-director','map':'SH_Arrakeen','floor':1}
        with patch('director_policy.urllib.request.urlopen') as opened:
            for extra in [{'host':'example.com'},{'map':'../other'},{'floor':True},{'floor':-1}]:
                with self.assertRaises(ValueError):apply({**valid,**extra})
            opened.assert_not_called()
