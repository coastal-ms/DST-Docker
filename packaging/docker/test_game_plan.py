import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parent))
from game_plan import COMPONENTS, memory_bytes, plan_world, public_plan
from world_template import validate_profile


class GamePlanTests(unittest.TestCase):
    def setUp(self):
        self.project='a'*32
        self.profile={'name':'Coastal Test','region':'North America','address':'127.0.0.1','gamePortBase':28777}
        self.database={'network':'dst-'+self.project+'-network','name':'dst-'+self.project+'-postgres','port':18932}
        self.template={'sha256':'example','partitions':[{'id':1,'map':'Survival_1'},{'id':2,'map':'Overmap'},{'id':8,'map':'DeepDesert_1'}],
                       'world':{'spec':{'serverGroup':{'template':{'spec':{'sets':[
                           {'map':'Survival_1','partitions':[1],'replicas':1,'resources':{'limits':{'memory':'12Gi'}}},
                           {'map':'Overmap','partitions':[2],'replicas':1,'resources':{'limits':{'memory':'2Gi'}}},
                           {'map':'DeepDesert_1','replicas':0,'resources':{'limits':{'memory':'15Gi'}}}]}}}}}}
        entries={archive:name for archive,name in COMPONENTS.values()}
        self.assets={'images':[{'archive':archive,'tags':['registry.funcom.com/funcom/self-hosting/'+name+':test']} for archive,name in entries.items()]}

    def plan(self):return plan_world(self.project,self.profile,self.template,self.assets,self.database)

    def test_explicit_map_memory_survives_a_fresh_world_plan_without_changing_stock_defaults(self):
        plan=plan_world(self.project,self.profile,self.template,self.assets,self.database,{'Survival_1':16*1024**3})
        self.assertEqual(plan['maps'][0]['memoryBytes'],16*1024**3)
        self.assertEqual(plan['initialMemoryBytes'],18*1024**3)
        self.assertEqual(self.plan()['maps'][0]['memoryBytes'],12*1024**3)
        with self.assertRaises(ValueError):plan_world(self.project,self.profile,self.template,self.assets,self.database,{'missing':16*1024**3})

    def test_zero_replica_maps_remain_available_and_limits_come_from_stock(self):
        plan=self.plan()
        self.assertEqual([row['map'] for row in plan['maps']],['Survival_1','Overmap','DeepDesert_1'])
        self.assertEqual(plan['maps'][2]['initialReplicas'],0)
        self.assertEqual(plan['maps'][2]['memoryBytes'],15*1024**3)
        self.assertEqual(plan['initialMemoryBytes'],14*1024**3)
        self.assertEqual(len(plan['games']),3)

    def test_range_overflow_database_collision_and_internal_overlap_are_rejected(self):
        self.profile['gamePortBase']=65500
        with self.assertRaises(ValueError):self.plan()
        self.profile['gamePortBase']=18932
        with self.assertRaises(ValueError):self.plan()
        self.profile['gamePortBase']=28777
        self.template['partitions'].append({'id':1001,'map':'Survival_1'})
        with self.assertRaises(ValueError):self.plan()

    def test_foreign_database_image_and_incomplete_map_catalogue_are_rejected(self):
        original=copy.deepcopy(self.assets)
        self.assets['images'][0]['tags']=['attacker/image:test']
        with self.assertRaises(ValueError):self.plan()
        self.assets=original
        self.database['network']='redblink-test-network'
        with self.assertRaises(ValueError):self.plan()
        self.database['network']='dst-'+self.project+'-network'
        self.template['partitions'].append({'id':9,'map':'UnaccountedMap'})
        with self.assertRaises(ValueError):self.plan()

    def test_public_review_has_no_internal_docker_settings(self):
        result=public_plan(self.plan())
        self.assertNotIn('images',result)
        self.assertNotIn('network',result)
        self.assertNotIn('names',result)

    def test_profile_rejects_malformed_hostnames_and_boolean_ports(self):
        for address in ['a..b','-bad.example','a.-bad','a.'*40+'-bad','x'*64+'.com','$(touch-file)']:
            with self.subTest(address=address):
                with self.assertRaises(ValueError):validate_profile({**self.profile,'address':address})
        for base in [True,0,65536]:
            with self.assertRaises(ValueError):validate_profile({**self.profile,'gamePortBase':base})
        for address in ['localhost','example.com','example.com.','192.168.1.2','::1']:
            self.assertEqual(validate_profile({**self.profile,'address':address})['address'],address)

    def test_memory_syntax_is_explicit_and_finite(self):
        self.assertEqual(memory_bytes('2Gi'),2147483648)
        for value in ['NaN','1.2Gi','0Gi','2G',True]:
            with self.assertRaises(ValueError):memory_bytes(value)


if __name__=='__main__':unittest.main()
