import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

import regis_compatibility as regis


PROJECT = 'a' * 32
IMAGE = 'sha256:' + 'b' * 64
OFFICIAL = 'registry.funcom.com/funcom/self-hosting/seabass-server:2173753-0-shipping'


class Fleet:
    def __init__(self):
        self.containers = {}; self.counter = 0; self.lifecycle_calls = []; self.fail_create = None; self.fail_cpu = False; self.external_start = False
        for partition in (1, 2, 8):
            name = 'game-' + str(partition)
            self.containers['old-' + name] = self.row('old-' + name, name, OFFICIAL, 256 * 1024**2, None)

    def row(self, identifier, component, image, memory, generation):
        return {'Id': identifier, 'Name': '/dst-' + PROJECT + '-' + component, 'Image': image,
                'Config': {'Labels': {'io.dst.managed': 'true', 'io.dst.project': PROJECT, 'io.dst.component': component, 'io.dst.generation': generation}},
                'HostConfig': {'Memory': memory, 'MemorySwap': memory, 'CpuPeriod': 100000, 'CpuQuota': 50000 if component == 'game-1' else 0, 'NanoCpus': 0},
                'State': {'Status': 'created'}, 'Mounts': [{'Destination': '/home/dune/server/DuneSandbox/Saved', 'Type': 'volume', 'Name': 'dst-' + PROJECT + '-' + component + '-saved'}]}

    def assert_owned(self, identifier, project, component):
        row = self.containers[identifier]
        assert project == PROJECT and row['Config']['Labels']['io.dst.component'] == component
        return row

    def request(self, method, path, body=None, expected=None):
        if method == 'GET' and path.startswith('/networks/'):
            return {'IPAM': {'Config': [{'Gateway': '172.30.0.1'}]}}
        if method == 'GET' and path.startswith('/containers/'):
            identifier = path.removeprefix('/containers/').removesuffix('/json')
            return self.containers.get(identifier) or next((row for row in self.containers.values() if row['Name'].lstrip('/') == identifier), None)
        if method == 'POST' and '/rename?' in path:
            identifier = path.split('/')[2]; self.containers[identifier]['Name'] = '/' + parse_qs(path.split('?', 1)[1])['name'][0]
            return
        raise AssertionError((method, path))

    def ensure_package_image(self, *args): pass

    def retire_component(self, identifier, project, component):
        row = self.assert_owned(identifier, project, component); assert row['State']['Status'] in {'created', 'exited'}
        row['Name'] += '-previous-' + str(self.counter); self.counter += 1
        return row['Name'].lstrip('/')

    def create_component(self, project, component, image, network, **spec):
        if self.fail_create == component and not self.external_start: raise ValueError('injected create failure')
        identifier = 'new-' + component + '-' + str(self.counter); self.counter += 1
        self.containers[identifier] = self.row(identifier, component, spec.get('regis_image') or image, spec['memory'], spec['generation'])
        if self.fail_create == component and self.external_start:
            self.containers[identifier]['State']['Status'] = 'running'
            raise ValueError('ambiguous create followed by external start')
        return identifier

    def upload_component_files(self, identifier, project, component, files):
        assert all('/Saved/' not in name for name in files), 'Tank changes must not upload Saved INIs'

    def set_component_cpu(self, identifier, project, component, cap):
        if self.fail_cpu: raise ValueError('injected CPU readback failure')
        self.containers[identifier]['HostConfig']['CpuQuota'] = round(cap * 100000) if cap else 0

    def lifecycle(self, *args): self.lifecycle_calls.append(args); raise AssertionError('Game lifecycle must not be invoked')


class RegisCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.state = {'id': PROJECT, 'desiredState': 'stopped', 'profile': {'name': 'fixture'},
            'operation': {'id': 'c' * 32, 'phase': 'running'}, 'worldPlan': {'network': 'dst-' + PROJECT + '-network',
                'images': {'game': {'image': OFFICIAL, 'archive': '/assets/official.tar'}},
                'games': [{'partition': i, 'map': 'DeepDesert_1' if i == 8 else 'Survival_1'} for i in (1, 2, 8)]},
            'services': {'game-' + str(i): {'id': 'old-game-' + str(i), 'phase': 'prepared'} for i in (1, 2, 8)}}
        self.engine = Fleet(); self.saved = []
        self.manager = SimpleNamespace(STATE=None, save=lambda state: self.saved.append(copy.deepcopy(state)), read_credentials=lambda state: {})
        self.builder = patch.object(regis, 'Builder'); self.mock_builder = self.builder.start(); self.mock_builder.return_value.prepare.return_value = IMAGE
        self.spec = patch.object(regis, 'game_spec', side_effect=lambda plan, partition, credentials, bridge, defaults: {
            'memory': 16 * 1024**3, 'volumes': [], 'environment': {}, 'files': {'dst-game.sh': {'data': 'wrapper'}}})
        self.mock_spec = self.spec.start()
        self.addCleanup(self.builder.stop); self.addCleanup(self.spec.stop)
        self.control = regis.Compatibility(self.state, self.engine, self.manager)

    def test_enable_replaces_only_stopped_hagga_and_preserves_ram_cpu_and_saved_payload(self):
        self.assertTrue(self.control.set(True)['enabled'])
        self.assertEqual(self.state['services']['game-8']['id'], 'old-game-8')
        for name in ('game-1', 'game-2'):
            row = self.engine.containers[self.state['services'][name]['id']]
            self.assertEqual(row['Image'], IMAGE); self.assertEqual(row['HostConfig']['Memory'], 256 * 1024**2)
            self.assertEqual(row['HostConfig']['CpuQuota'], 50000 if name == 'game-1' else 0)
        self.assertTrue(all(call.args[-1] == {} for call in self.mock_spec.call_args_list))
        self.assertNotIn('pendingRegisChange', self.state); self.assertNotIn('generationChange', self.state)
        self.assertEqual(self.engine.lifecycle_calls, [])

    def test_disable_requires_ack_then_restores_official_images_without_starting(self):
        self.control.set(True)
        before = copy.deepcopy(self.state)
        with self.assertRaisesRegex(ValueError, 'Acknowledge'): self.control.set(False)
        self.assertEqual(before, self.state)
        self.state['operation']['id'] = 'd' * 32
        self.assertFalse(self.control.set(False, True)['enabled'])
        self.assertTrue(all(self.engine.containers[self.state['services'][name]['id']]['Image'] == OFFICIAL for name in ('game-1', 'game-2')))
        self.assertEqual(self.engine.lifecycle_calls, [])

    def test_running_world_or_any_running_game_fails_before_preparation(self):
        self.state['desiredState'] = 'running'
        with self.assertRaises(ValueError): self.control.set(True)
        self.state['desiredState'] = 'stopped'; self.engine.containers['old-game-8']['State']['Status'] = 'running'
        with self.assertRaises(ValueError): self.control.set(True)
        self.mock_builder.assert_not_called(); self.assertFalse(self.saved)

    def test_creation_and_cpu_failures_restore_previous_containers_and_setting(self):
        initial = copy.deepcopy(self.state)
        for failure in ('create', 'cpu'):
            with self.subTest(failure=failure):
                self.state = copy.deepcopy(initial); self.engine = Fleet(); self.saved = []
                self.control = regis.Compatibility(self.state, self.engine, self.manager)
                if failure == 'create': self.engine.fail_create = 'game-2'
                else: self.engine.fail_cpu = True
                with self.assertRaises(ValueError): self.control.set(True)
                self.assertEqual([self.state['services']['game-' + str(i)]['id'] for i in (1, 2, 8)], ['old-game-1', 'old-game-2', 'old-game-8'])
                self.assertNotIn('regisSupport', self.state); self.assertNotIn('pendingRegisChange', self.state)
                self.assertEqual(self.engine.lifecycle_calls, [])

    def test_external_start_during_ambiguous_create_is_never_implicitly_stopped(self):
        self.engine.fail_create = 'game-1'; self.engine.external_start = True
        with self.assertRaises(ValueError): self.control.set(True)
        self.assertIn('pendingRegisChange', self.state)
        self.assertEqual(self.engine.lifecycle_calls, [])
        with self.assertRaisesRegex(ValueError, 'Stop every game'): self.control.recover()
        for row in self.engine.containers.values(): row['State']['Status'] = 'created'
        self.control.recover()
        self.assertEqual(self.state['services']['game-1']['id'], 'old-game-1')
        self.assertNotIn('pendingRegisChange', self.state)

    def test_recovery_after_commit_before_pending_clear_restores_recorded_previous_policy(self):
        self.control.set(True)
        history = self.state['generationHistory'][-1]
        self.state['pendingRegisChange'] = {'id': 'c' * 32, 'generation': history['id'], 'previous': None, 'enabled': True, 'phase': 'committing'}
        self.control.recover()
        self.assertNotIn('regisSupport', self.state)
        self.assertEqual(self.state['services']['game-1']['id'], 'old-game-1')
        self.assertEqual(self.engine.lifecycle_calls, [])

    def test_pending_disable_without_ack_cannot_trigger_recovery_side_effects(self):
        self.state['pendingRegisChange'] = {'enabled': True, 'previous': None}
        before = copy.deepcopy(self.state)
        with self.assertRaisesRegex(ValueError, 'Acknowledge'): self.control.set(False)
        self.assertEqual(self.state, before); self.assertFalse(self.saved)

    def test_restart_after_rollback_before_pending_clear_verifies_restored_adapters(self):
        self.control.set(True)
        history = self.state['generationHistory'][-1]
        self.state['pendingRegisChange'] = {'id': 'c' * 32, 'generation': history['id'], 'previous': None, 'enabled': True, 'phase': 'committing'}
        original_save = self.manager.save
        def fail_after_rollback(state):
            original_save(state)
            if not state.get('generationChange') and state['generationHistory'][-1]['phase'] == 'rolled-back':
                raise OSError('fixture crash after rollback persistence')
        self.manager.save = fail_after_rollback
        with self.assertRaises(OSError): self.control.recover()
        self.manager.save = original_save
        self.assertIn('pendingRegisChange', self.state)
        self.control.recover()
        self.assertNotIn('pendingRegisChange', self.state)
        self.assertNotIn('regisSupport', self.state)
        self.assertEqual(self.state['services']['game-1']['id'], 'old-game-1')
        self.assertEqual(self.engine.lifecycle_calls, [])

    def test_image_policy_never_applies_to_other_maps_and_pending_state_blocks_starts(self):
        self.state['regisSupport'] = {'enabled': True, 'image': IMAGE}
        self.assertEqual(regis.apply_image_policy(self.state, 8, {}), {})
        self.assertEqual(regis.apply_image_policy(self.state, 1, {})['regis_image'], IMAGE)
        self.state['pendingRegisChange'] = {'phase': 'recovering'}
        with self.assertRaisesRegex(ValueError, 'pending Tank change'): regis.assert_prepared_images(self.state, self.engine)

    def test_support_refuses_stopped_or_pending_world_without_executing_a_hash_command(self):
        self.engine.exec_internal = Mock()
        self.state['regisSupport'] = {'enabled': True, 'image': IMAGE}
        self.assertFalse(regis.support(self.state, self.engine)['enabled'])
        self.state['operation']['phase'] = 'completed'
        self.assertFalse(regis.support(self.state, self.engine)['enabled'])
        self.engine.exec_internal.assert_not_called()

    def test_support_requires_fresh_ready_heartbeat_and_all_four_matching_files(self):
        self.state['regisSupport'] = {'enabled': True, 'image': IMAGE}
        self.state['desiredState'] = 'running'; self.state['operation']['phase'] = 'completed'
        self.state['services']['director'] = {'id': 'director'}
        for name in ('game-1', 'game-2'): self.engine.containers['old-' + name]['Image'] = IMAGE
        self.engine.containers['old-game-1']['State'] = {'Status': 'running', 'StartedAt': '1970-01-01T00:01:40Z'}
        self.engine.game_heartbeats = Mock(return_value={1: {'ready': True, 'observedAt': 99}})
        self.engine.exec_internal = Mock(return_value='')
        with patch.object(regis, 'inspect_compatibility_image', return_value={'Id': IMAGE}), patch.object(regis, 'accepted_source', return_value=({'build': '2173753', 'patchedExecutableSha256': 'c' * 64}, {})):
            self.assertFalse(regis.support(self.state, self.engine)['enabled'])
            self.engine.exec_internal.assert_not_called()
            self.engine.game_heartbeats.return_value[1]['observedAt'] = 101
            self.assertFalse(regis.support(self.state, self.engine)['enabled'])
            expected = {'/home/dune/server/DuneSandbox/Binaries/Linux/DuneSandboxServer-Linux-Shipping': 'c' * 64}
            expected.update({'/home/dune/server/DuneSandbox/Content/Paks/' + regis.OVERLAY + '.' + ext: value for ext, value in regis.OVERLAY_HASHES.items()})
            self.engine.exec_internal.return_value = '\n'.join(sha + '  ' + path for path, sha in expected.items())
            self.assertTrue(regis.support(self.state, self.engine)['enabled'])

    def test_normal_update_refuses_enabled_or_pending_tanks_before_staging_or_stopping(self):
        import world_update
        for flag in ('regisSupport', 'pendingRegisChange'):
            state = copy.deepcopy(self.state); state[flag] = {'enabled': True}
            engine = Mock(); manager = Mock()
            with self.assertRaisesRegex(ValueError, 'before a normal server update'):
                world_update.NativeUpdate(state, engine, manager).apply('26332623')
            engine.assert_not_called(); manager.save.assert_not_called()
            self.assertEqual(engine.method_calls, [])


if __name__ == '__main__': unittest.main()


class MultipleHaggaCompatibilityTests(unittest.TestCase):
    def test_all_numbered_hagga_maps_get_the_selected_image_and_deep_deserts_do_not(self):
        state={'worldPlan':{'games':[{'partition':1,'map':'Survival_1'},{'partition':2,'map':'Survival_2'},{'partition':8,'map':'DeepDesert_1'},{'partition':9,'map':'DeepDesert_2'}]},'services':{f'game-{n}':{} for n in (1,2,8,9)},'regisSupport':{'enabled':True,'image':IMAGE}}
        self.assertEqual(regis.hagga_components(state),['game-1','game-2'])
        for partition in (1,2):self.assertEqual(regis.apply_image_policy(state,partition,{})['regis_image'],IMAGE)
        for partition in (8,9):self.assertNotIn('regis_image',regis.apply_image_policy(state,partition,{}))
