import unittest
from unittest.mock import Mock,patch
import map_modes
import manager
from scale_protocol import native_director_ini


class MapModesTests(unittest.TestCase):
    def test_overmap_warmup_idle_delay_and_unknown_players(self):
        self.assertEqual(map_modes.overmap_floor(1,0,None,100),(True,None))
        self.assertEqual(map_modes.overmap_floor(0,0,None,100),(None,100))
        self.assertEqual(map_modes.overmap_floor(0,0,100,399),(None,100))
        self.assertEqual(map_modes.overmap_floor(0,0,100,400),(False,100))
        self.assertEqual(map_modes.overmap_floor(0,1,100,401),(None,100))
        self.assertEqual(map_modes.overmap_floor(None,0,100,401),(None,None))
        self.assertEqual(map_modes.overmap_floor(0,None,100,401),(None,100))

    def test_disabled_director_projection_and_core_mode(self):
        row={'map':'DeepDesert_1','partitions':[8],'initialReplicas':0}
        config=native_director_ini('[ DeepDesert_1 ]\nMinServers=1\n',{'maps':[row]},{'game-8':True},{'DeepDesert_1':'disabled'})
        self.assertIn('MinServers=0',config)
        self.assertIn('EnableAutomaticInstanceScaling=false',config)
        self.assertEqual(map_modes.mode_for({'mapModes':{'Survival_1':'disabled'}},{'map':'Survival_1','partitions':[1],'initialReplicas':1}),'core')

    def test_modes_do_not_stop_running_maps_and_core_changes_are_rejected(self):
        state={'worldPlan':{'maps':[{'map':'DeepDesert_1','partitions':[8],'initialReplicas':0},{'map':'Survival_1','partitions':[1],'initialReplicas':1}]}}
        engine=Mock()
        with patch.object(manager,'set_map_floor') as floor,patch.object(manager,'save'):
            manager.set_map_mode(state,engine,'DeepDesert_1','disabled')
            floor.assert_called_once_with(state,engine,'DeepDesert_1',False)
            self.assertEqual(state['mapModes']['DeepDesert_1'],'disabled')
            with self.assertRaises(ValueError):manager.set_map_mode(state,engine,'Survival_1','disabled')
        engine.assert_not_called()

    def test_failed_mode_write_retains_previous_selection(self):
        state={'mapModes':{'DeepDesert_1':'dynamic'},'worldPlan':{'maps':[{'map':'DeepDesert_1','partitions':[8],'initialReplicas':0}]}}
        with patch.object(manager,'set_map_floor',side_effect=ValueError('failure')),patch.object(manager,'save'):
            with self.assertRaises(ValueError):manager.set_map_mode(state,Mock(),'DeepDesert_1','always-on')
        self.assertEqual(state['mapModes']['DeepDesert_1'],'dynamic')
        self.assertEqual(state['pendingMapMode'],{'map':'DeepDesert_1','mode':'always-on'})

    def test_scheduler_raises_floor_for_overmap_players_and_never_stops_unknown_occupancy(self):
        state={'desiredState':'running','worldPlan':{'maps':[{'map':'DeepDesert_1','partitions':[8],'initialReplicas':0}],
               'games':[{'map':'Overmap','partition':2},{'map':'DeepDesert_1','partition':8}]},'mapModes':{'DeepDesert_1':'overmap-active'}}
        observed={'services':[{'component':'game-2','state':'running','players':1},{'component':'game-8','state':'running','players':0}]}
        def floor(s,e,m,enabled):s.setdefault('manualPins',{})['game-8']=enabled
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'public_state',return_value=observed),patch.object(manager,'set_map_floor',side_effect=floor) as change,patch.object(manager,'save'):
            manager.map_mode_tick(Mock(),100)
            self.assertTrue(state['manualPins']['game-8'])
            observed['services'][0]['players']=0
            manager.map_mode_tick(Mock(),110)
            manager.map_mode_tick(Mock(),409)
            self.assertEqual(change.call_count,1)
            observed['services'][1].pop('players')
            manager.map_mode_tick(Mock(),411)
            self.assertEqual(change.call_count,1)
            observed['services'][1]['players']=0
            manager.map_mode_tick(Mock(),412)
            self.assertFalse(state['manualPins']['game-8'])

    def test_disabled_maps_reject_new_director_demand(self):
        state={'mapModes':{'DeepDesert_1':'disabled'},'desiredState':'running','scaler':{'coreAdapterApplied':True}}
        with patch.object(manager,'parse_patch',return_value=({'map':'DeepDesert_1'},[8])),patch.object(manager,'desired_partitions',return_value=[]):
            with self.assertRaisesRegex(ValueError,'disabled'):manager.request_scale(state,Mock(),'map',[])


if __name__=='__main__':unittest.main()
