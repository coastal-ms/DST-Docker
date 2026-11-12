import unittest
import json
import socket
import tempfile
import threading
from pathlib import Path
from unittest.mock import Mock,patch
import map_modes
import manager
from scale_protocol import native_director_ini


class MapModesTests(unittest.TestCase):
    def test_return_to_overmap_cancels_a_stop_before_signalling(self):
        state={'mapModes':{'SH_HarkoVillage':'overmap-active'},'worldPlan':{'games':[{'map':'SH_HarkoVillage','partition':4}]},'scalePending':{}}
        request={'availablePartitions':[4],'partitions':[],'previousTargets':{}}
        with patch.object(manager,'follow_overmap_demand',return_value=True),patch.object(manager,'set_map_floor') as floor,patch.object(manager,'control_map') as control,patch.object(manager,'save'):
            manager.apply_scale(state,Mock(),request)
            floor.assert_called_once_with(state,unittest.mock.ANY,'SH_HarkoVillage',True)
            control.assert_called_once_with(state,unittest.mock.ANY,4,True,automatic=True)

    def test_return_during_shutdown_restarts_after_draining(self):
        state={'mapModes':{'SH_HarkoVillage':'overmap-active'},'worldPlan':{'games':[{'map':'SH_HarkoVillage','partition':4}]},'scalePending':{}}
        request={'availablePartitions':[4],'partitions':[],'previousTargets':{}}
        with patch.object(manager,'follow_overmap_demand',side_effect=[False,True]),patch.object(manager,'set_map_floor'),patch.object(manager,'control_map') as control,patch.object(manager,'save'):
            manager.apply_scale(state,Mock(),request)
            self.assertEqual([call.args[3] for call in control.call_args_list],[False,True])
            self.assertEqual(state['scalePending']['phase'],'completed')

    def test_warm_but_stopped_maps_are_queued_together_with_all_partitions(self):
        rows=[{'map':'SH_Arrakeen','partitions':[3]},{'map':'SH_HarkoVillage','partitions':[4]},{'map':'DeepDesert_1','partitions':[8,18]}]
        state={'id':'a'*32,'manualPins':{'game-3':True,'game-4':True,'game-8':True,'game-18':True},
               'mapTargets':{'game-3':'running','game-4':'stopped','game-8':'running','game-18':'stopped'},
               'services':{'game-3':{'id':'three'},'game-4':{'id':'four'},'game-8':{'id':'eight'}}}
        engine=Mock(spec=manager.Engine)
        engine.assert_owned.side_effect=lambda identifier,*args:{'State':{'Status':'exited' if identifier=='four' else 'running'}}
        with patch.object(manager,'save'),patch.object(manager.threading,'Thread') as thread:
            manager.queue_follow_overmap_starts(state,engine,rows)
            self.assertEqual(state['scalePending']['partitions'],[4,18])
            self.assertEqual(state['mapTargets']['game-4'],'running')
            self.assertEqual(state['mapTargets']['game-18'],'running')
            self.assertTrue(state['manualPins']['game-3'])
            thread.return_value.start.assert_called_once()

    def test_shared_timer_resets_when_anyone_returns_to_overmap(self):
        rows=[{'map':'SH_Arrakeen','partitions':[3],'initialReplicas':0},{'map':'SH_HarkoVillage','partitions':[4],'initialReplicas':0}]
        state={'id':'a'*32,'desiredState':'running','worldPlan':{'maps':rows,'games':[{'map':'Overmap','partition':2},{'map':'SH_Arrakeen','partition':3},{'map':'SH_HarkoVillage','partition':4}]},
               'mapModes':{row['map']:'overmap-active' for row in rows},'manualPins':{'game-3':True,'game-4':True}}
        counts={2:0,3:0,4:0}
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'scheduler_occupancy',return_value=counts),patch.object(manager,'queue_follow_overmap_starts'),patch.object(manager,'set_map_floor') as floor,patch.object(manager,'save'):
            manager.map_mode_tick(Mock(),100)
            counts[2]=1;manager.map_mode_tick(Mock(),150)
            self.assertIsNone(state['overmapEmptySince'])
            counts[2]=0;manager.map_mode_tick(Mock(),160);manager.map_mode_tick(Mock(),219)
            floor.assert_not_called()
            manager.map_mode_tick(Mock(),220)
            self.assertEqual(floor.call_count,2)

    def test_every_follow_overmap_map_and_partition_uses_the_same_grace(self):
        maps=[{'map':name,'partitions':parts,'initialReplicas':0} for name,parts in
              [('SH_Arrakeen',[3]),('SH_HarkoVillage',[4]),('DeepDesert_1',[8,18])]]
        state={'id':'a'*32,'desiredState':'running','worldPlan':{'maps':maps,
               'games':[{'map':'Overmap','partition':2}]+[{'map':row['map'],'partition':p} for row in maps for p in row['partitions']]},
               'mapModes':{row['map']:'overmap-active' for row in maps}}
        counts={2:1,3:0,4:0,8:0,18:0}
        def floor(s,e,name,enabled):
            for p in next(row['partitions'] for row in maps if row['map']==name):
                s.setdefault('manualPins',{})['game-'+str(p)]=enabled
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'queue_follow_overmap_starts'),patch.object(manager,'scheduler_occupancy',return_value=counts),patch.object(manager,'set_map_floor',side_effect=floor) as changed,patch.object(manager,'save'):
            manager.map_mode_tick(Mock(),100)
            self.assertTrue(all(state['manualPins']['game-'+str(p)] for p in [3,4,8,18]))
            counts[2]=0
            manager.map_mode_tick(Mock(),110);manager.map_mode_tick(Mock(),169)
            self.assertEqual(changed.call_count,3)
            counts[18]=1
            manager.map_mode_tick(Mock(),170)
            self.assertFalse(state['manualPins']['game-3']);self.assertFalse(state['manualPins']['game-4'])
            self.assertTrue(state['manualPins']['game-8']);self.assertTrue(state['manualPins']['game-18'])
            counts[18]=0
            manager.map_mode_tick(Mock(),171)
            self.assertFalse(state['manualPins']['game-8']);self.assertFalse(state['manualPins']['game-18'])

    def test_slow_client_does_not_block_other_management_requests(self):
        entered=threading.Event();release=threading.Event()
        def dispatch(request):
            if request['action']=='slow':
                entered.set();release.wait(3)
            return {'responsive':True}
        with tempfile.TemporaryDirectory() as directory,patch.object(manager,'dispatch',side_effect=dispatch):
            path=str(Path(directory)/'manager.sock')
            with manager.ManagementServer(path,manager.Handler) as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    with socket.socket(socket.AF_UNIX) as first:
                        first.connect(path);first.sendall(b'{"action":"slow"}\n')
                        self.assertTrue(entered.wait(1))
                        with socket.socket(socket.AF_UNIX) as second:
                            second.settimeout(1);second.connect(path)
                            second.sendall(b'{"action":"status"}\n')
                            self.assertTrue(json.loads(second.recv(4096))['ok'])
                finally:
                    release.set();server.shutdown();thread.join(2)

    def test_scheduler_uses_online_database_count_despite_empty_heartbeat_list(self):
        identity='A'*22
        state={'id':'a'*32,'database':{'id':'db'},'worldPlan':{'games':[{'partition':2},{'partition':3}]},
               'services':{'director':{'id':'director'},'game-2':{'id':'overmap'}}}
        engine=Mock(spec=manager.Engine)
        engine.game_heartbeats.return_value={2:{'serverId':identity,'observedAt':100,'players':0}}
        engine.assert_owned.return_value={'State':{'Status':'running','StartedAt':'1970-01-01T00:00:50Z'}}
        engine.exec_internal.return_value='BEGIN\nSET\n'+json.dumps({identity:1})+'\nCOMMIT\n'
        self.assertEqual(manager.scheduler_occupancy(state,engine),{2:1,3:0})
        command=engine.exec_internal.call_args.args[-1][-1]
        self.assertIn('BEGIN READ ONLY',command)
        self.assertIn("online_status::text <> 'Offline'",command)
        self.assertIn('statement_timeout',command)

    def test_old_process_identity_is_unknown_not_empty(self):
        state={'id':'a'*32,'worldPlan':{'games':[{'partition':2}]},
               'services':{'director':{'id':'director'},'game-2':{'id':'overmap'}}}
        engine=Mock(spec=manager.Engine)
        engine.game_heartbeats.return_value={2:{'serverId':'A'*22,'observedAt':40,'players':0}}
        engine.assert_owned.return_value={'State':{'Status':'running','StartedAt':'1970-01-01T00:00:50Z'}}
        self.assertEqual(manager.scheduler_occupancy(state,engine),{2:None})
        engine.exec_internal.assert_not_called()

    def test_status_responds_while_scheduler_holds_mutation_lock(self):
        state={'id':'a'*32}
        with manager.LOCK,patch.object(manager,'project_state',return_value=state),patch.object(manager,'public_state',return_value={'services':[]}) as observed:
            self.assertEqual(manager.dispatch({'action':'status'},Mock()),{'services':[]})
            observed.assert_called_once_with(state,unittest.mock.ANY,observe=False)

    def test_scheduler_occupancy_io_runs_without_mutation_lock(self):
        state={'id':'a'*32,'desiredState':'running','worldPlan':{'maps':[{'map':'SH_Arrakeen','partitions':[3],'initialReplicas':0}],
               'games':[{'map':'Overmap','partition':2},{'map':'SH_Arrakeen','partition':3}]},'mapModes':{'SH_Arrakeen':'overmap-active'}}
        def occupancy(*args):
            self.assertFalse(manager.LOCK.locked())
            return {2:1,3:0}
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'queue_follow_overmap_starts'),patch.object(manager,'scheduler_occupancy',side_effect=occupancy),patch.object(manager,'set_map_floor') as floor,patch.object(manager,'save'):
            manager.map_mode_tick(Mock(),100)
            floor.assert_called_once_with(state,unittest.mock.ANY,'SH_Arrakeen',True)

    def test_overmap_releases_empty_map_after_one_minute(self):
        self.assertEqual(map_modes.overmap_floor(1,0,None,100),(True,None))
        self.assertEqual(map_modes.overmap_floor(0,0,None,100),(None,100))
        self.assertEqual(map_modes.overmap_floor(0,0,100,159),(None,100))
        self.assertEqual(map_modes.overmap_floor(0,0,100,160),(False,100))
        self.assertEqual(map_modes.overmap_floor(0,1,100,161),(None,100))
        self.assertEqual(map_modes.overmap_floor(None,0,100,161),(None,None))
        self.assertEqual(map_modes.overmap_floor(0,None,100,161),(None,100))

    def test_disabled_director_projection_and_core_mode(self):
        row={'map':'DeepDesert_1','partitions':[8],'initialReplicas':0}
        config=native_director_ini('[ DeepDesert_1 ]\nMinServers=1\n',{'maps':[row]},{'game-8':True},{'DeepDesert_1':'disabled'})
        self.assertIn('MinServers=0',config)
        self.assertIn('EnableAutomaticInstanceScaling=false',config)
        self.assertEqual(map_modes.mode_for({'mapModes':{'Survival_1':'disabled'}},{'map':'Survival_1','partitions':[1],'initialReplicas':1}),'core')

    def test_modes_do_not_stop_running_maps_and_core_changes_are_rejected(self):
        state={'worldPlan':{'maps':[{'map':'DeepDesert_1','partitions':[8],'initialReplicas':0},{'map':'Survival_1','partitions':[1],'initialReplicas':1}]}}
        engine=Mock(spec=manager.Engine)
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
        with patch.object(manager,'project_state',return_value=state),patch.object(manager,'queue_follow_overmap_starts'),patch.object(manager,'scheduler_occupancy',side_effect=lambda *args:{2:observed['services'][0].get('players'),8:observed['services'][1].get('players')}),patch.object(manager,'set_map_floor',side_effect=floor) as change,patch.object(manager,'save'):
            manager.map_mode_tick(Mock(),100)
            self.assertTrue(state['manualPins']['game-8'])
            observed['services'][0]['players']=0
            manager.map_mode_tick(Mock(),110)
            manager.map_mode_tick(Mock(),169)
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
