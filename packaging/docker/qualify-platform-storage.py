"""Run as the unprivileged app against disposable /data/state and /tmp mounts."""
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path('/data/state')
CACHE_OWNER_DIR = ROOT / 'DuneServer'
CACHE = CACHE_OWNER_DIR / 'platform-cache'
DATABASE = CACHE / 'platform-cache-v1.sqlite'
HELPER = '/opt/dst/app/tools/platform/DunePlatformStore'
assert os.geteuid() == 10001 and ROOT.resolve() == ROOT
assert not os.environ.get('DST_PLATFORM_SELF_TEST') and not CACHE_OWNER_DIR.exists()


def call(command='migrate', *extra):
    result = subprocess.run([HELPER, '--command', command, *extra], capture_output=True, text=True, timeout=30)
    return result.returncode, json.loads(result.stdout or result.stderr)


def reset():
    # Only the fixed disposable mount's own test directory is removed.
    assert CACHE_OWNER_DIR.parent == ROOT and str(CACHE_OWNER_DIR) == '/data/state/DuneServer'
    if CACHE_OWNER_DIR.is_symlink():
        CACHE_OWNER_DIR.unlink()
    elif CACHE_OWNER_DIR.exists():
        shutil.rmtree(CACHE_OWNER_DIR)


code, reply = call()
assert code == 0 and reply['ok']
assert CACHE.stat().st_mode & 0o777 == 0o700
assert DATABASE.stat().st_mode & 0o777 == 0o600
assert call('integrity')[1]['quickCheck'] == 'ok'
checks = ['fixed-path-migration', 'private-permissions', 'integrity']
reset()

outside = ROOT / 'outside-test-file'
outside.write_bytes(b'external-fixture-must-stay-unchanged')
for kind in ('database-symlink', 'database-hardlink', 'wal-symlink', 'parent-symlink', 'writable-parent'):
    reset()
    if kind == 'parent-symlink':
        target = ROOT / 'outside-test-directory'
        target.mkdir(exist_ok=True)
        CACHE_OWNER_DIR.symlink_to(target, target_is_directory=True)
    else:
        CACHE.mkdir(parents=True, mode=0o700)
        if kind == 'database-symlink': DATABASE.symlink_to(outside)
        if kind == 'database-hardlink': os.link(outside, DATABASE)
        if kind == 'wal-symlink': Path(str(DATABASE) + '-wal').symlink_to(outside)
        if kind == 'writable-parent': CACHE_OWNER_DIR.chmod(0o777)
    code, reply = call()
    assert code != 0 and reply['ok'] is False, (kind, reply)
    assert outside.read_bytes() == b'external-fixture-must-stay-unchanged'
    checks.append(kind + '-rejected')
reset()
assert call('migrate', '--database', '/tmp/arbitrary-cache.sqlite')[0] != 0
assert not Path('/tmp/arbitrary-cache.sqlite').exists()
print(json.dumps({'productionBoundary': checks, 'arbitraryPathRejected': True, 'uid': os.geteuid(), 'outsideBytesPreserved': True}))

