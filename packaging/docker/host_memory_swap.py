"""Fixed-purpose host helper for the explicitly confirmed Memory Swap option.

Only DST-owned swap storage and marked configuration entries are managed.
The helper is invoked in an owned, network-isolated root container. No caller
can supply a command, host pathname, image or filesystem root through the API.
"""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import uuid

from memory_swap import GIB


class HostSwap:
    def __init__(self, project, root=Path('/host'), run=None):
        if not re.fullmatch('[a-f0-9]{32}', project):
            raise ValueError('Invalid swap ownership identity.')
        self.project, self.root = project, Path(root)
        self.directory = self.root / 'var/lib/dst-docker' / project
        self.swap = self.directory / 'swapfile'
        self.record = self.directory / 'memory-swap.json'
        self.host_swap = '/var/lib/dst-docker/' + project + '/swapfile'
        self.sysctl = self.root / 'etc/sysctl.d/99-dst-docker-memory-swap.conf'
        self.fstab = self.root / 'etc/fstab'
        self.marker = '# DST Docker Memory Swap ' + project
        self.run = run or self.host_command

    def host_command(self, *args):
        result = subprocess.run(['chroot', str(self.root), *args], capture_output=True,
                                text=True, timeout=600)
        if result.returncode:
            raise ValueError((result.stderr.strip() or 'The host swap command failed.')[-600:])
        return result.stdout.strip()

    def existing_record(self):
        if not self.record.exists():
            return {}
        self.regular(self.record)
        result = json.loads(self.record.read_text())
        if result.get('project') != self.project:
            raise ValueError('The host swap record belongs to another installation.')
        return result

    @staticmethod
    def regular(path):
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1:
            raise ValueError('The host swap path is not an ordinary root-owned file.')

    def checked_directories(self):
        # Refuse symlink traversal before a root helper creates or changes files.
        for relative in ['var', 'var/lib', 'var/lib/dst-docker',
                         'var/lib/dst-docker/' + self.project, 'etc', 'etc/sysctl.d']:
            target = self.root / relative
            if target.exists() or target.is_symlink():
                st = target.lstat()
                if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
                    raise ValueError('Host swap storage must use root-owned directories without symlinks.')
            else:
                target.mkdir(mode=0o700)

    def swaps(self):
        rows = []
        # Read in the host-root context so procfs renders owned filenames in
        # that root, including when the helper itself uses a /host bind mount.
        text=self.run('cat','/proc/swaps') or (self.root / 'proc/swaps').read_text()
        for line in text.splitlines()[1:]:
            columns = line.split()
            if len(columns) >= 5:
                # procfs renders filenames in the reader's mount namespace;
                # our host root can therefore appear with its /host prefix.
                name=columns[0]
                prefix=str(self.root).rstrip('/')
                if name.startswith(prefix+'/'):name=name[len(prefix):]
                rows.append({'file': name, 'bytes': int(columns[2]) * 1024,
                             'usedBytes': int(columns[3]) * 1024})
        return rows

    def swappiness(self):
        return int((self.root / 'proc/sys/vm/swappiness').read_text().strip())

    def status(self):
        rows = self.swaps()
        managed = next((r for r in rows if r['file'] == self.host_swap), None)
        disk = shutil.disk_usage(self.directory if self.directory.exists() else self.root / 'var/lib')
        reserve = max(25 * GIB, disk.total // 10)
        reusable = self.swap.stat().st_blocks * 512 if self.swap.is_file() and not self.swap.is_symlink() else 0
        mem = next(int(line.split()[1]) * 1024 for line in (self.root / 'proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:'))
        return {'hostPoolActive': managed is not None, 'managedSwapBytes': managed['bytes'] if managed else 0,
                'existingSwapBytes': sum(r['bytes'] for r in rows if r['file'] != self.host_swap),
                'physicalMemoryBytes': mem, 'safeAvailableDiskGiB': max(0, (disk.free + reusable - reserve) // GIB),
                'swappiness': self.swappiness(), 'swapFile': self.host_swap,
                'hostRecord': self.existing_record()}

    def write_record(self, record):
        temporary = self.record.with_name('.swap-' + uuid.uuid4().hex + '.pending')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, 'w') as stream:
                json.dump(record, stream); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, self.record)
        finally:
            temporary.unlink(missing_ok=True)

    def write_fstab(self, enabled):
        if self.fstab.exists():
            self.regular(self.fstab)
            text = self.fstab.read_text()
        else:
            text = ''
        lines = [line for line in text.splitlines() if not line.endswith(self.marker)]
        if enabled:
            lines.append(self.host_swap + ' none swap sw 0 0 ' + self.marker)
        # Keep the existing inode, including host-specific mount attributes.
        self.fstab.write_text('\n'.join(lines) + ('\n' if lines else ''))

    def verify_sysctl_owner(self, require_owned=True):
        if self.sysctl.exists() or self.sysctl.is_symlink():
            if self.sysctl.is_symlink() and not require_owned:return False
            try:self.regular(self.sysctl)
            except ValueError:
                if require_owned:raise
                return False
            first = self.sysctl.read_text().splitlines()[:1]
            owned=first == [self.marker]
            if not owned and require_owned:
                raise ValueError('Another installation or administrator owns the swap sysctl file.')
            return owned
        return False

    @contextlib.contextmanager
    def lock(self):
        self.checked_directories()
        path = self.root / 'var/lib/dst-docker/memory-swap.lock'
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, 'w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield
        except BlockingIOError:
            raise ValueError('Another host swap operation is running.') from None

    def configure(self, policy):
        with self.lock():
            owned_sysctl=self.verify_sysctl_owner(require_owned=policy['enabled'])
            if self.fstab.exists() or self.fstab.is_symlink():self.regular(self.fstab)
            previous = self.existing_record()
            if policy['enabled']:
                pool, swappiness = policy['poolGiB'], policy['swappiness']
                current = self.status()
                if not pool and not current['existingSwapBytes']:
                    raise ValueError('There is no existing host swap. Choose a managed pool or prepare host swap first.')
                if (self.swap.exists() or self.swap.is_symlink()) and not previous:
                    raise ValueError('An unowned file exists at the managed swap path; no change was made.')
                if pool > current['safeAvailableDiskGiB']:
                    raise ValueError('Keep at least 25 GiB or 10% of host disk free before creating swap.')
                if pool:
                    filesystem = self.run('findmnt', '-n', '-o', 'FSTYPE', '--target', '/' + self.directory.relative_to(self.root).as_posix())
                    if filesystem not in {'ext2', 'ext3', 'ext4', 'xfs'}:
                        raise ValueError('Managed swap requires ext4/xfs storage. Configure existing host swap for this filesystem.')
                record = {'project': self.project, 'originalSwappiness': previous.get('originalSwappiness', self.swappiness()),
                          **policy, 'phase': 'applying'}
                self.write_record(record)
                active = current['hostPoolActive']
                if self.swap.exists() or self.swap.is_symlink():
                    self.regular(self.swap)
                    if self.swap.stat().st_size != pool * GIB:
                        if active:
                            self.run('swapoff', self.host_swap)
                            if self.status()['hostPoolActive']:raise ValueError('The managed swap pool is still active; its file was preserved.')
                        self.swap.unlink(); active = False
                if pool:
                    if not self.swap.exists():
                        descriptor = os.open(self.swap, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                        try: os.posix_fallocate(descriptor, 0, pool * GIB)
                        finally: os.close(descriptor)
                    if not active:
                        self.run('mkswap', self.host_swap)
                        self.run('swapon', self.host_swap)
                    if not self.status()['hostPoolActive']:
                        raise ValueError('The managed swap file was prepared but activation was not verified; it was preserved for recovery.')
                self.write_fstab(pool > 0)
                self.sysctl.write_text(self.marker + '\nvm.swappiness = ' + str(swappiness) + '\n')
                self.run('sysctl', '-w', 'vm.swappiness=' + str(swappiness))
                record['phase'] = 'completed'; self.write_record(record)
            else:
                if (self.swap.exists() or self.swap.is_symlink()) and not previous:
                    raise ValueError('The swap file has no owned record; it was not removed.')
                if self.status()['hostPoolActive']:
                    self.run('swapoff', self.host_swap)
                    if self.status()['hostPoolActive']:raise ValueError('The managed swap pool is still active; its file was preserved.')
                if self.swap.exists() or self.swap.is_symlink():
                    self.regular(self.swap); self.swap.unlink()
                self.write_fstab(False)
                if owned_sysctl:self.sysctl.unlink(missing_ok=True)
                if owned_sysctl and previous and self.swappiness() == previous.get('swappiness'):
                    self.run('sysctl', '-w', 'vm.swappiness=' + str(previous['originalSwappiness']))
                self.record.unlink(missing_ok=True)
            return self.status()


def main():
    import sys
    from memory_swap import validate
    request = json.loads(sys.argv[1])
    helper = HostSwap(request['project'])
    try:
        result = helper.status() if request['action'] == 'status' else helper.configure(validate(request))
        report = {'ok': True, 'data': result}
    except Exception as error:
        report = {'ok': False, 'error': str(error)}
    Path('/tmp/dst-result.json').write_text(json.dumps(report))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
