import copy
import unittest
from unittest.mock import Mock, patch
import resource_policy as policy
import manager

GIB=1024**3


def world():
    return {'id':'a'*32,'desiredState':'stopped','services':{'game-1':{'id':'owned'}},
            'worldPlan':{'maps':[{'map':'Survival_1','partitions':[1],'initialReplicas':1,'memoryBytes':4*GIB},
                                 {'map':'Story','partitions':[2,3],'initialReplicas':0,'memoryBytes':2*GIB}],
                         'games':[{'map':'Survival_1','partition':1},{'map':'Story','partition':2},{'map':'Story','partition':3}]}}


def change():
    return {'memoryGiB':12,'cpuCount':4,'maps':[{'map':'Survival_1','memoryGiB':6,'cpus':2},
                                             {'map':'Story','memoryGiB':4,'cpus':1}]}


class ResourcePolicyTests(unittest.TestCase):
    def setUp(self):
        self.host={'memoryBytes':32*GIB,'availableBytes':24*GIB,'cpus':8}
        self.engine=Mock(spec=manager.Engine);self.engine.assert_owned.return_value={'State':{'Status':'exited'}}

    def test_valid_allocations_leave_host_and_service_headroom(self):
        self.assertEqual(policy.validate_change(world(),change(),self.host),change())

    def test_host_capacity_respects_container_memory_and_cpu_ceilings(self):
        def read(path):
            if str(path)=='/proc/meminfo':return 'MemTotal: 33554432 kB\nMemAvailable: 25165824 kB\n'
            if str(path).endswith('memory.max'):return str(8*GIB)
            if str(path).endswith('cpu.max'):return '200000 100000'
            raise AssertionError('Unexpected source')
        with patch.object(policy.Path,'read_text',read),patch.object(policy.os,'sched_getaffinity',return_value=set(range(8))):
            self.assertEqual(policy.host_capacity(),{'memoryBytes':8*GIB,'availableBytes':8*GIB,'cpus':2})

    def test_quarter_gib_map_sizes_are_supported(self):
        request=change();request['maps'][1]['memoryGiB']=.5
        self.assertEqual(policy.validate_change(world(),request,self.host),request)

    def test_invalid_types_bounds_duplicates_and_oversubscription_are_rejected(self):
        changes=[]
        for key,value in [('memoryGiB',True),('memoryGiB',31),('memoryGiB',2),('cpuCount',float('nan')),('cpuCount',9),('cpuCount',True)]:
            request=change();request[key]=value;changes.append(request)
        request=change();request['maps'][0]['memoryGiB']=11;changes.append(request)
        request=change();request['maps'][1]=copy.deepcopy(request['maps'][0]);changes.append(request)
        request=change();request['maps'][0]['cpus']=0;changes.append(request)
        request=change();request['maps'][0]['map']='other';changes.append(request)
        for request in changes:
            with self.subTest(request=request),self.assertRaises(ValueError):policy.validate_change(world(),request,self.host)

    def test_saved_start_targets_are_included_before_applying(self):
        state=world();state['mapTargets']={'game-2':'running','game-3':'running'}
        with self.assertRaisesRegex(ValueError,'startup maps'):policy.validate_change(state,change(),self.host)

    def test_resource_save_updates_verified_container_limits_and_persists_without_lifecycle(self):
        state=world()
        with patch.object(manager,'save') as save,patch.object(policy,'host_capacity',return_value=self.host):
            result=manager.set_resources(state,self.engine,change())
        self.engine.set_component_memory.assert_called_once_with('owned','a'*32,'game-1',6*GIB)
        self.engine.set_component_cpu.assert_called_once_with('owned','a'*32,'game-1',2)
        self.engine.lifecycle.assert_not_called();self.assertEqual(save.call_count,2)
        self.assertEqual(state['resourcePolicy'],{'memoryGiB':12,'cpuCount':4})
        self.assertEqual(state['worldPlan']['maps'][0]['memoryBytes'],6*GIB)
        self.assertEqual(result['maps'][0]['cpus'],2);self.assertNotIn('pendingResourceChange',state)

    def test_live_world_is_never_stopped_or_resized_implicitly(self):
        state=world();state['desiredState']='running'
        with patch.object(policy,'host_capacity',return_value=self.host),patch.object(manager,'save') as save:
            with self.assertRaisesRegex(ValueError,'Stop the battlegroup'):manager.set_resources(state,self.engine,change())
        save.assert_not_called();self.engine.set_component_memory.assert_not_called()

    def test_failed_engine_update_retains_recoverable_intent_and_blocks_new_choice(self):
        state=world();self.engine.set_component_cpu.side_effect=manager.EngineError('interrupted')
        with patch.object(policy,'host_capacity',return_value=self.host),patch.object(manager,'save'):
            with self.assertRaises(manager.EngineError):manager.set_resources(state,self.engine,change())
            self.assertEqual(state['pendingResourceChange'],change());self.assertNotIn('resourcePolicy',state)
            request=change();request['memoryGiB']=14
            with self.assertRaisesRegex(ValueError,'Retry the pending'):manager.set_resources(state,self.engine,request)
            self.engine.set_component_cpu.side_effect=None
            manager.set_resources(state,self.engine,change())
        self.assertNotIn('pendingResourceChange',state)

    def test_running_maps_count_against_ram_and_cpu_admission(self):
        state=world();state['resourcePolicy']={'memoryGiB':8,'cpuCount':2};state['mapCpuOverrides']={'Survival_1':2,'Story':1}
        self.engine.assert_owned.return_value={'State':{'Status':'running'}}
        policy.admit(state,self.engine,[1])
        with self.assertRaisesRegex(ValueError,'exceed'):policy.admit(state,self.engine,[2])
        state['pendingResourceChange']=change()
        with self.assertRaisesRegex(ValueError,'pending'):policy.admit(state,self.engine,[1])

    def test_memory_only_updates_cannot_bypass_configured_budget(self):
        state=world();state['resourcePolicy']={'memoryGiB':8,'cpuCount':2}
        with self.assertRaisesRegex(ValueError,'Settings'):manager.set_map_memory(state,self.engine,'Survival_1',16)
