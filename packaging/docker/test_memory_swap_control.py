import copy
import json
import unittest
from unittest.mock import Mock, patch

import memory_swap_control as control
from engine import Engine


class MemorySwapControlTests(unittest.TestCase):
    def setUp(self):
        control._CACHE.clear()
        self.state={'id':'a'*32,'services':{'game-1':{'id':'owned-game'}},
                    'worldPlan':{'maps':[{'map':'Survival_1','memoryBytes':16*1024**3}]},
                    'operation':{'id':'b'*32,'phase':'running'}}
        self.engine=Mock(spec=Engine)
        self.engine.assert_owned.return_value={'State':{'Status':'exited'},'HostConfig':{'Memory':16*1024**3,'MemorySwap':16*1024**3}}
        self.engine.create_host_swap_job.return_value='owned-host-job'
        self.host={'hostPoolActive':False,'existingSwapBytes':10*1024**3,
                   'swappiness':10,'safeAvailableDiskGiB':40}
        self.engine.backup_report.return_value={'ok':True,'data':self.host}
        self.request={'enabled':True,'perServerGiB':2,'poolGiB':0,'swappiness':10,
                      'confirmation':'ENABLE MEMORY SWAP'}
        self.snapshots=[]
        self.save=lambda state:self.snapshots.append(copy.deepcopy(state))

    def test_live_enable_changes_only_swap_and_persists_intent_before_host_execution(self):
        result=control.configure(self.state,self.engine,self.save,self.request)
        self.engine.set_component_swap.assert_called_once_with('owned-game','a'*32,'game-1',
            {'enabled':True,'perServerGiB':2,'poolGiB':0,'swappiness':10})
        self.engine.set_component_memory.assert_not_called()
        self.assertEqual(self.state['worldPlan']['maps'][0]['memoryBytes'],16*1024**3)
        self.assertIn('pendingSwapChange',self.snapshots[0])
        self.assertNotIn('pendingSwapChange',self.state)
        self.assertTrue(result['enabled'])
        # Worker stores this result inside operation; it must never recurse.
        self.state['operation']['result']=result
        json.dumps(self.state)

    def test_container_failure_retains_intent_and_restore_previous_can_disable_partial_enable(self):
        self.engine.set_component_swap.side_effect=ValueError('kernel limit update interrupted')
        with self.assertRaisesRegex(ValueError,'interrupted'):
            control.configure(self.state,self.engine,self.save,self.request)
        self.assertIn('pendingSwapChange',self.state)
        self.engine.set_component_swap.side_effect=None
        result=control.recover(self.state,self.engine,self.save,True)
        self.assertFalse(result['enabled'])
        self.assertEqual(self.state['memorySwap']['enabled'],False)
        self.assertNotIn('pendingSwapChange',self.state)

    def test_recorded_running_helper_is_observed_instead_of_started_again_after_restart(self):
        pending={'hostJob':'existing-job'}
        self.engine.assert_owned.side_effect=[{'State':{'Status':'running'}},{'State':{'Status':'exited'}}]
        with patch.object(control.time,'sleep'):
            result=control.host_job(self.state,self.engine,self.save,self.request,pending)
        self.assertEqual(result,self.host)
        self.engine.create_host_swap_job.assert_not_called()
        self.engine.lifecycle.assert_not_called()

    def test_foreign_or_inaccessible_container_prevents_any_swap_limit_update(self):
        self.engine.backup_report.return_value={'ok':False,'error':'host ownership mismatch'}
        with self.assertRaisesRegex(ValueError,'ownership'):
            control.configure(self.state,self.engine,self.save,self.request)
        self.engine.set_component_swap.assert_not_called()
        self.assertEqual(self.state['pendingSwapChange']['phase'],'failed')

    def test_new_policy_is_rejected_while_recovery_is_pending(self):
        self.state['pendingSwapChange']={'desired':{'enabled':False},'previous':{'enabled':False}}
        with self.assertRaisesRegex(ValueError,'Retry or restore'):
            control.configure(self.state,self.engine,self.save,self.request)
        self.engine.create_host_swap_job.assert_not_called()

    def test_unsupported_host_is_rejected_before_creating_pending_recovery_state(self):
        self.engine.assert_swap_supported.side_effect=ValueError('swap accounting is unavailable')
        with self.assertRaisesRegex(ValueError,'accounting'):
            control.configure(self.state,self.engine,self.save,self.request)
        self.assertNotIn('pendingSwapChange',self.state)
        self.assertEqual(self.snapshots,[])
        self.engine.create_host_swap_job.assert_not_called()


if __name__=='__main__':unittest.main()
