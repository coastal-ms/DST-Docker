import copy
import unittest
from scale_protocol import scale_resource,parse_patch,native_director_ini,snapshot,party_sharing_ini


class ScalingTests(unittest.TestCase):
    def test_party_sharing_changes_only_the_selected_setting_and_preserves_other_ini_text(self):
        source='; manual header\r\n[ CB_Story_DestroyedZanovar ]\r\nMinServers=0\r\n; keep this\r\nMaxParties=1\r\n\r\n[ SH_Arrakeen ]\r\nMaxParties=3\r\n'
        shared=party_sharing_ini(source,'CB_Story_DestroyedZanovar',True)
        self.assertNotIn('MaxParties=1',shared)
        self.assertIn('; keep this\r\n\r\n[ SH_Arrakeen ]\r\nMaxParties=3\r\n',shared)
        isolated=party_sharing_ini(shared,'CB_Story_DestroyedZanovar',False)
        self.assertEqual(isolated.count('MaxParties=1'),1)
        self.assertEqual(party_sharing_ini(isolated,'CB_Story_DestroyedZanovar',False),isolated)
        with self.assertRaises(ValueError):party_sharing_ini(source,'SH_Arrakeen',False)
    def setUp(self):
        self.maps=[{'map':'Survival_1','partitions':[1],'initialReplicas':1},{'map':'SH_Arrakeen','partitions':[3],'initialReplicas':0}]
        self.state={'worldId':'sh-fixture','worldPlan':{'maps':self.maps},'database':{'name':'own-postgres'},'desiredState':'running'}
    def test_catalogue_matches_stock_resource_names_and_partition_semantics(self):
        warm=scale_resource(self.state,self.maps[0]);cold=scale_resource(self.state,self.maps[1])
        self.assertEqual(warm['metadata']['name'],'sh-fixture-survival-1')
        self.assertEqual(warm['spec']['partitions'],[1]);self.assertEqual(cold['spec']['replicas'],0)
        self.assertEqual(cold['metadata']['annotations']['igw.funcom.com/map-name'],'SH_Arrakeen')
    def test_director_patch_cannot_select_a_foreign_map_or_write_other_fields(self):
        patch=[{'op':'replace','path':'/spec/replicas','value':1},{'op':'replace','path':'/spec/partitions','value':[3]}]
        before=copy.deepcopy(self.state)
        info,partitions=parse_patch(self.state,'sh-fixture-sh-arrakeen',patch)
        self.assertEqual(info['map'],'SH_Arrakeen');self.assertEqual(partitions,[3]);self.assertEqual(before,self.state)
        for name,value in [('foreign-sh-arrakeen',patch),('sh-fixture-sh-arrakeen',[{'op':'replace','path':'/spec/password','value':'bad'}]),
                           ('sh-fixture-sh-arrakeen',[{'op':'replace','path':'/spec/replicas','value':1},{'op':'replace','path':'/spec/partitions','value':[1]}]),
                           ('sh-fixture-sh-arrakeen',[{'op':'replace','path':'/spec/replicas','value':True}])]:
            with self.assertRaises(ValueError):parse_patch(self.state,name,value)
        self.assertEqual(before,self.state)
    def test_private_projection_never_exposes_the_database_administrative_role(self):
        template={'world':{'metadata':{},'spec':{'database':{'template':{'spec':{'deployment':{'spec':{'superPassword':'admin-secret','superUser':'postgres','worldPartitions':[]}}}}}}}}
        result=snapshot(self.state,template,'app-secret')
        deployment=result['battlegroup']['spec']['database']['template']['spec']['deployment']['spec']
        self.assertEqual(deployment['password'],'app-secret');self.assertNotIn('superPassword',deployment);self.assertNotIn('superUser',deployment)
    def test_native_policy_is_idempotent_and_keeps_unrelated_ini_settings(self):
        source='; custom note\n[ Battlegroup ]\nAuthorizationPreset=BattlegroupInternal\n[ SH_Arrakeen ]\nMaxParties=1\nMinServers = 7\n'
        result=native_director_ini(source,{'maps':self.maps})
        self.assertIn('; custom note',result);self.assertIn('MaxParties=1',result)
        self.assertIn('[ Survival_1 ]\nEnableAutomaticInstanceScaling=true\nMinServers=1',result)
        self.assertIn('MinServers=0',result)
        self.assertEqual(native_director_ini(result,{'maps':self.maps}),result)


if __name__=='__main__':unittest.main()
