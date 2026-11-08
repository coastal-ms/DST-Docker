import unittest

from memory_swap import GIB, recommended_pool, total_limit, validate


class MemorySwapPolicyTests(unittest.TestCase):
    def test_existing_host_swap_offsets_the_managed_pool(self):
        self.assertEqual(recommended_pool(2, 2, 10 * GIB), 0)
        self.assertEqual(recommended_pool(2, 8, 10 * GIB), 6)
        self.assertEqual(recommended_pool(16, 35, 0), 32)
        self.assertEqual(recommended_pool(1, 0, 0), 2)

    def test_custom_allowance_adds_to_ram_and_default_tracks_changed_ram(self):
        policy = {'enabled': True, 'perServerGiB': 2}
        self.assertEqual(total_limit(16 * GIB, policy), 18 * GIB)
        self.assertEqual(total_limit(2 * GIB, policy), 4 * GIB)
        self.assertEqual(total_limit(16 * GIB, {'enabled': False}), 32 * GIB)
        self.assertEqual(total_limit(3 * GIB), 6 * GIB)

    def test_explicit_confirmation_and_integer_ranges_precede_host_changes(self):
        request = {'enabled': True, 'perServerGiB': 2, 'poolGiB': 0,
                   'swappiness': 10, 'confirmation': 'ENABLE MEMORY SWAP'}
        self.assertEqual(validate(request)['poolGiB'], 0)
        for field, value in [('enabled', 1), ('perServerGiB', True),
                             ('poolGiB', 33), ('swappiness', -1),
                             ('confirmation', 'DISABLE MEMORY SWAP')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate({**request, field: value})
        self.assertEqual(validate({'enabled': False, 'confirmation': 'DISABLE MEMORY SWAP'}),
                         {'enabled': False, 'perServerGiB': 0, 'poolGiB': 0, 'swappiness': 10})


if __name__ == '__main__':
    unittest.main()
