import copy
import unittest
from unittest.mock import Mock,patch
import manager


class WorldNameTests(unittest.TestCase):
    def setUp(self):
        self.state={'phase':'database-ready','profile':{'name':'Before','address':'127.0.0.1','region':'North America','gamePortBase':28777},
                    'desiredState':'running','mapTargets':{'game-8':'running'},'mapMemoryOverrides':{'Survival_1':16*1024**3},'mapCpuOverrides':{'Survival_1':.5}}

    def test_running_rename_reuses_existing_stop_configure_and_start_without_changing_allocations_or_targets(self):
        old=copy.deepcopy(self.state);calls=[]
        def stop(state,engine):calls.append('stop');state['desiredState']='stopped'
        def configure(state,engine,profile):calls.append('configure');self.assertEqual(state['desiredState'],'stopped');state['profile']=profile
        def start(state,engine):calls.append('start');state['desiredState']='running'
        with patch.object(manager,'stop_services',side_effect=stop),patch.object(manager,'configure_world',side_effect=configure),patch.object(manager,'start_services',side_effect=start):
            manager.rename_world(self.state,Mock(),' After ')
        self.assertEqual(calls,['stop','configure','start']);self.assertEqual(self.state['profile'],{**old['profile'],'name':'After'})
        for key in ['mapTargets','mapMemoryOverrides','mapCpuOverrides']:self.assertEqual(self.state[key],old[key])

    def test_stopped_world_is_not_started_and_identical_name_has_no_side_effects(self):
        self.state['desiredState']='stopped'
        with patch.object(manager,'stop_services') as stop,patch.object(manager,'start_services') as start,patch.object(manager,'configure_world') as configure:
            manager.rename_world(self.state,Mock(),'Before');configure.assert_not_called()
            manager.rename_world(self.state,Mock(),'After');configure.assert_called_once();stop.assert_not_called();start.assert_not_called()

    def test_invalid_name_is_rejected_before_disruption_and_failed_configuration_is_not_started(self):
        with patch.object(manager,'stop_services') as stop:
            for name in [None,'','x'*51,'a\nb']:
                with self.assertRaises(ValueError):manager.rename_world(self.state,Mock(),name)
            stop.assert_not_called()
        with patch.object(manager,'stop_services'),patch.object(manager,'configure_world',side_effect=ValueError('fixture failure')),patch.object(manager,'start_services') as start:
            with self.assertRaisesRegex(ValueError,'fixture failure'):manager.rename_world(self.state,Mock(),'After')
            start.assert_not_called()


if __name__=='__main__':unittest.main()
