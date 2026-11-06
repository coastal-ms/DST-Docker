import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('observer', Path(__file__).with_name('observer.py'))
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class ObserverTests(unittest.TestCase):
    def test_working_set_uses_cgroup_cache_without_negative_values(self):
        self.assertEqual(observer.memory_values({'memory_stats': {'usage': 100, 'limit': 200, 'stats': {'inactive_file': 30}}}),
                         {'usedBytes': 70, 'limitBytes': 200, 'rawBytes': 100})
        self.assertEqual(observer.memory_values({'memory_stats': {'usage': 10, 'stats': {'total_inactive_file': 50}}})['usedBytes'], 0)

    def test_snapshot_omits_unrelated_containers_and_sensitive_metadata(self):
        calls = []
        def read(path):
            calls.append(path)
            if path == '/info': return {'MemTotal': 1000, 'NCPU': 4, 'ServerVersion': 'test', 'Secrets': 'omit'}
            if path.startswith('/containers/json'):
                return [{'Id': 'a', 'Names': ['/map'], 'Image': 'registry.funcom.com/funcom/self-hosting/server:1',
                         'State': 'running', 'Labels': {'private': 'omit'}, 'Mounts': ['omit']},
                        {'Id': 'b', 'Names': ['/unrelated'], 'Image': 'other:1', 'State': 'running'}]
            if path.startswith('/containers/a/stats?'): return {'memory_stats': {'usage': 100, 'limit': 200}}
            raise AssertionError(path)
        snapshot = observer.collect(read)
        self.assertEqual(len(snapshot['containers']), 1)
        self.assertEqual(snapshot['containers'][0]['memory']['usedBytes'], 100)
        self.assertNotIn('omit', str(snapshot))
        self.assertEqual(len(calls), 3)

    def test_stopped_and_racing_containers_keep_honest_sample_state(self):
        def read(path):
            if path == '/info': return {}
            if path.startswith('/containers/json'):
                return [{'Id': state, 'Image': 'registry.funcom.com/funcom/self-hosting/server:1', 'State': state}
                        for state in ['running', 'exited']]
            raise RuntimeError('container stopped before sample')
        snapshot = observer.collect(read)
        self.assertEqual([row['memory'] for row in snapshot['containers']], [None, None])
        self.assertTrue(snapshot['containers'][0]['sampleUnavailable'])


if __name__ == '__main__': unittest.main()
