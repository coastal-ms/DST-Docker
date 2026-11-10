import copy
import unittest
from unittest.mock import Mock,patch
import manager


class RestartPlanUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.plan={'profile':{'address':'127.0.0.1'},'ports':{'director':29777},
                   'databaseName':'owned-db','databasePort':18932,'memorySwap':None}
        previous=copy.deepcopy(self.plan);previous.pop('memorySwap')
        self.state={'id':'a'*32,'phase':'database-ready','partitionsPrepared':True,
                    'profile':{},'database':{'name':'owned-db','port':18932},
                    'worldPlan':previous,'desiredState':'running',
                    'operation':{'id':'b'*32,'action':'services.restart','phase':'running'}}

    def environment(self):
        return patch.multiple(manager,read_template=Mock(return_value={}),assets_state=Mock(return_value={}),
                              plan_world=Mock(return_value=self.plan),save=Mock())

    def test_old_journal_without_swap_metadata_is_compatible_with_off(self):
        original=copy.deepcopy(self.state)
        with self.environment():
            _,plan=manager.validate_connection_plan(self.state)
        self.assertEqual(plan,self.plan)
        self.assertEqual(self.state,original)

    def test_real_address_port_and_swap_policy_changes_still_fail_preflight(self):
        for key,value in [('profile',{'address':'192.0.2.9'}),('ports',{'director':29999}),
                          ('memorySwap',{'enabled':True,'perServerGiB':2})]:
            with self.subTest(key=key),self.environment():
                manager.plan_world.return_value={**self.plan,key:value}
                with self.assertRaisesRegex(ValueError,'connection plan differs'):
                    manager.validate_connection_plan(self.state)

    def test_restart_validates_legacy_plan_before_stop_and_start(self):
        calls=[]
        with self.environment(),patch.object(manager,'stop_services',side_effect=lambda *args:calls.append('stop')),patch.object(manager,'start_services',side_effect=lambda *args:calls.append('start')):
            manager.run_operation(self.state,Mock(),{'action':'services.restart'})
        self.assertEqual(calls,['stop','start'])
        self.assertEqual(self.state['operation']['phase'],'completed')

    def test_conflicting_plan_never_stops_the_running_world(self):
        with self.environment(),patch.object(manager,'stop_services') as stop,patch.object(manager,'start_services') as start:
            manager.plan_world.return_value={**self.plan,'ports':{'director':29999}}
            manager.run_operation(self.state,Mock(),{'action':'services.restart'})
        stop.assert_not_called();start.assert_not_called()
        self.assertEqual(self.state['desiredState'],'running')
        self.assertEqual(self.state['operation']['phase'],'failed')


if __name__=='__main__':unittest.main()
