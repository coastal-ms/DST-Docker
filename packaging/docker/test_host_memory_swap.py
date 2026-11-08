import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from host_memory_swap import HostSwap
from memory_swap import GIB


class HostMemorySwapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for directory in ['var/lib', 'etc/sysctl.d', 'proc/sys/vm']:
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / 'proc/swaps').write_text('Filename Type Size Used Priority\n/admin-swap file 10485760 0 -2\n')
        (self.root / 'proc/meminfo').write_text('MemTotal: 33554432 kB\n')
        (self.root / 'proc/sys/vm/swappiness').write_text('60\n')
        (self.root / 'etc/fstab').write_text('# administrator entry\n/admin-swap none swap sw 0 0\n')
        self.calls = []
        self.helper = HostSwap('a' * 32, self.root, self.run_command)
        self.disk = patch('host_memory_swap.shutil.disk_usage', return_value=type('Disk', (), {'total': 100 * GIB, 'free': 80 * GIB})())
        self.disk.start(); self.addCleanup(self.disk.stop)

    def run_command(self, *args):
        self.calls.append(args)
        if args[0] == 'findmnt': return 'ext4'
        if args[0] == 'sysctl': (self.root / 'proc/sys/vm/swappiness').write_text(args[-1].split('=')[1])
        if args[0] == 'swapon':
            with (self.root / 'proc/swaps').open('a') as stream:
                stream.write(self.helper.host_swap + ' file 1048576 0 -3\n')
        if args[0] == 'swapoff':
            file = self.root / 'proc/swaps'
            file.write_text('\n'.join(line for line in file.read_text().splitlines() if not line.startswith(args[1] + ' ')) + '\n')
        return ''

    def policy(self, pool=0):
        return {'enabled': True, 'poolGiB': pool, 'perServerGiB': 2, 'swappiness': 10}

    def test_existing_host_swap_needs_no_project_file_and_disable_restores_our_swappiness(self):
        original = (self.root / 'etc/fstab').read_text()
        status = self.helper.configure(self.policy())
        self.assertFalse(status['hostPoolActive']); self.assertFalse(self.helper.swap.exists())
        self.assertEqual(status['existingSwapBytes'], 10 * GIB)
        self.assertEqual(status['swappiness'], 10)
        self.assertNotIn('swapoff', [call[0] for call in self.calls])
        self.helper.configure({'enabled': False})
        self.assertEqual(self.helper.swappiness(), 60)
        self.assertEqual((self.root / 'etc/fstab').read_text(), original)
        self.assertIn('/admin-swap', (self.root / 'proc/swaps').read_text())

    def test_disable_preserves_an_administrators_later_swappiness_change(self):
        self.helper.configure(self.policy())
        (self.root / 'proc/sys/vm/swappiness').write_text('25')
        self.helper.configure({'enabled': False})
        self.assertEqual(self.helper.swappiness(), 25)

    def test_disable_can_restore_our_policy_without_removing_an_administrators_replacement_file(self):
        self.helper.configure(self.policy())
        self.helper.sysctl.write_text('# administrator replacement\nvm.swappiness = 10\n')
        self.helper.configure({'enabled':False})
        self.assertIn('administrator replacement',self.helper.sysctl.read_text())
        self.assertEqual(self.helper.swappiness(),10)
        self.assertFalse(self.helper.record.exists())

    def test_managed_pool_preserves_unrelated_fstab_and_failed_swapoff_preserves_own_file(self):
        with patch('host_memory_swap.os.posix_fallocate', side_effect=lambda fd, offset, size: os.ftruncate(fd, size)):
            result = self.helper.configure(self.policy(1))
        self.assertTrue(result['hostPoolActive'])
        self.assertEqual(self.helper.swap.stat().st_size, GIB)
        self.assertEqual(self.helper.swap.stat().st_mode & 0o777, 0o600)
        self.assertIn('/admin-swap none swap sw 0 0', self.helper.fstab.read_text())
        def fail(*args):
            if args[0] == 'swapoff': raise ValueError('Host RAM cannot evacuate swap yet')
            return self.run_command(*args)
        self.helper.run = fail
        with self.assertRaisesRegex(ValueError, 'evacuate'):
            self.helper.configure({'enabled': False})
        self.assertTrue(self.helper.swap.exists())
        self.assertIn(self.helper.marker, self.helper.fstab.read_text())
        self.helper.run = self.run_command
        self.helper.configure({'enabled': False})
        self.assertFalse(self.helper.swap.exists())
        self.assertIn('/admin-swap', (self.root / 'proc/swaps').read_text())

    def test_unowned_swap_file_and_symlink_storage_are_rejected_without_commands(self):
        self.helper.checked_directories()
        self.helper.swap.write_text('administrator data')
        with self.assertRaisesRegex(ValueError, 'unowned'):
            self.helper.configure(self.policy())
        self.assertEqual(self.helper.swap.read_text(), 'administrator data')
        self.assertTrue(all(call[0]=='cat' for call in self.calls))
        self.helper.swap.unlink(); self.helper.directory.rmdir()
        self.helper.directory.symlink_to(self.root / 'etc', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'without symlinks'):
            self.helper.configure(self.policy())

    def test_another_installations_sysctl_is_not_replaced(self):
        self.helper.sysctl.write_text('# administrator policy\nvm.swappiness = 15\n')
        with self.assertRaisesRegex(ValueError, 'administrator owns'):
            self.helper.configure(self.policy())
        self.assertIn('administrator policy', self.helper.sysctl.read_text())
        self.assertFalse(self.helper.record.exists())

    def test_procfs_host_mount_prefix_still_identifies_only_our_pool(self):
        with (self.root/'proc/swaps').open('a') as stream:
            stream.write(str(self.root)+self.helper.host_swap+' file 1048576 0 -3\n')
        result=self.helper.status()
        self.assertTrue(result['hostPoolActive'])
        self.assertEqual(result['managedSwapBytes'],GIB)
        self.assertEqual(result['existingSwapBytes'],10*GIB)


if __name__ == '__main__': unittest.main()
