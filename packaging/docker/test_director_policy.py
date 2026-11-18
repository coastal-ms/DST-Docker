import json
import unittest
import urllib.error
from unittest.mock import Mock,patch
from director_policy import apply


class PolicyTests(unittest.TestCase):
    def test_starting_director_is_retried_and_an_applied_floor_needs_no_override(self):
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock()
        response.read.return_value=json.dumps({'instancedMaps':{'Survival_1':{'cfg':{'minServers':0},'webOverrideCfg':{'playerHardCap':42}}}}).encode()
        with patch('director_policy.urllib.request.urlopen',side_effect=[urllib.error.URLError('not ready'),response]) as opened,patch('director_policy.time.sleep'):
            self.assertTrue(apply({'host':'dst-'+'a'*32+'-director','map':'Survival_1','floor':0})['applied'])
        self.assertEqual(opened.call_count,2)
        self.assertTrue(all(isinstance(call.args[0],str) for call in opened.call_args_list))

    def test_permanent_http_failure_is_not_retried(self):
        with patch('director_policy.urllib.request.urlopen',side_effect=urllib.error.HTTPError('http://fixture',401,'denied',{},None)) as opened:
            with self.assertRaises(urllib.error.HTTPError):apply({'host':'dst-'+'a'*32+'-director','map':'Survival_1','floor':0})
        self.assertEqual(opened.call_count,1)

    def test_startup_retry_has_a_deadline(self):
        with patch('director_policy.urllib.request.urlopen',side_effect=urllib.error.URLError('not ready')),patch('director_policy.time.monotonic',side_effect=[0,31]):
            with self.assertRaisesRegex(ValueError,'director is still starting'):apply({'host':'dst-'+'a'*32+'-director','map':'Survival_1','floor':0})

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

    def test_floor_release_submits_without_waiting_for_activation(self):
        response=Mock()
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock()
        response.read.return_value=json.dumps({'instancedMaps':{'SH_HarkoVillage':{
            'cfg':{'minServers':1},'webOverrideCfg':{'minServers':1}}}}).encode()
        def busy_director(request, timeout):
            if timeout < 3:
                raise TimeoutError('Director request exceeded its time budget')
            return response

        with patch('director_policy.urllib.request.urlopen',side_effect=busy_director) as opened:
            self.assertTrue(apply({'host':'dst-'+'a'*32+'-director','map':'SH_HarkoVillage',
                                   'floor':0,'confirm':False})['applied'])
        self.assertEqual(opened.call_count,2)
        self.assertEqual(json.loads(opened.call_args.args[0].data)['ClassicalInstancingGroupConfig'],{'MinServers':0})

    def test_foreign_destinations_and_invalid_values_never_make_a_request(self):
        valid={'host':'dst-'+'a'*32+'-director','map':'SH_Arrakeen','floor':1}
        with patch('director_policy.urllib.request.urlopen') as opened:
            for extra in [{'host':'example.com'},{'map':'../other'},{'floor':True},{'floor':-1}]:
                with self.assertRaises(ValueError):apply({**valid,**extra})
            opened.assert_not_called()
