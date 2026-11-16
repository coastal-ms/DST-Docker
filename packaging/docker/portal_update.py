"""Installed, owner-account systemd service for DST product updates (not game updates)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid


def bootstrap(source):
    text = (source / 'bootstrap.sh').read_text(encoding='utf-8')
    code = text.split("<<'DST_BOOTSTRAP_PY'\n", 1)[1].rsplit('\nDST_BOOTSTRAP_PY', 1)[0]
    module = {'__name__': 'dst_update_bootstrap'}
    exec(compile(code, str(source / 'bootstrap.sh'), 'exec'), module)
    return module


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d+\.\d+\.\d+', value):
        raise ValueError('The Docker release has an unsupported version.')
    return tuple(int(part) for part in value.removeprefix('v').split('.'))


def atomic(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


class Updater:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root / 'portal-update'
        self.lock = threading.Lock()
        self.check_lock = threading.Lock()
        self.cached = None
        path = self.directory / 'operation.json'
        self.operation = json.loads(path.read_text()) if path.exists() else None

    def source(self):
        source = (self.root / 'current').resolve(strict=True)
        if source.parent != self.root / 'releases':
            raise ValueError('This is not a managed DST installation.')
        return source

    def current(self):
        return json.loads((self.source() / 'packaging/docker/release.json').read_text())['version']

    def check(self, force=False):
        with self.check_lock:
            if force or not self.cached or time.time() - self.cached['checkedAt'] >= 6 * 3600:
                module = bootstrap(self.source())
                opener = module['urllib'].request.build_opener(module['Redirect']())
                auth = module['token']()
                download = lambda path: json.loads(module['download'](opener, path, auth, 1024**2, 5))
                release = download('/releases/latest')
                tag = release['tag_name']
                version(tag)
                if release.get('draft') or release.get('prerelease'):
                    raise ValueError('Choose a published stable Docker release.')
                ref = download('/git/ref/tags/' + tag)['object']
                for _ in range(5):
                    if ref.get('type') == 'commit': break
                    if ref.get('type') != 'tag' or not re.fullmatch(r'[0-9a-f]{40}', ref.get('sha', '')):
                        raise ValueError('The release reference is invalid.')
                    ref = download('/git/tags/' + ref['sha'])['object']
                if ref.get('type') != 'commit' or not re.fullmatch(r'[0-9a-f]{40}', ref.get('sha', '')):
                    raise ValueError('The release must resolve to an exact commit.')
                self.cached = {'latestVersion': tag[1:] if tag.startswith('v') else tag,
                               'tag': tag, 'commit': ref['sha'], 'checkedAt': time.time()}
            current = self.current()
            return {**self.cached, 'currentVersion': current,
                    'available': version(self.cached['latestVersion']) > version(current)}

    def compose(self, *args, input=None):
        command = ['docker', 'compose', '-f', str(self.source() / 'compose.yaml')]
        for name in ('https.compose.json', 'mirror.compose.json', 'host.compose.json', 'update.compose.json'):
            if (self.root / name).exists(): command += ['-f', str(self.root / name)]
        return subprocess.check_output([*command, *args], input=input, timeout=45)

    def manager(self, action, identifier):
        container = self.compose('ps', '-q', 'dst').decode().strip()
        if not re.fullmatch(r'[a-f0-9]{12,64}', container): raise ValueError('The DST portal must be running.')
        raw = subprocess.check_output(['docker', 'exec', '-i', container, 'python3',
                                      '/opt/dst/packaging/docker/manager-client.py'],
                                     input=json.dumps({'action': action, 'id': identifier}).encode(), timeout=45)
        response = json.loads(raw)
        if not response.get('ok'): raise ValueError(response.get('error', 'Server maintenance is unavailable.'))

    def record(self, **patch):
        with self.lock:
            self.operation = {**(self.operation or {}), **patch}
            atomic(self.directory / 'operation.json', self.operation)

    def install(self, request):
        if set(request) != {'action', 'tag', 'commit', 'confirmation'} or request['confirmation'] != 'UPDATE DST DOCKER':
            raise ValueError('Confirm the selected DST Docker update.')
        if not self.lock.acquire(blocking=False): raise ValueError('An update is already being prepared.')
        identifier = None
        try:
            if self.operation and self.operation['phase'] == 'running': raise ValueError('An update is already running.')
            selected = self.check(force=True)
            if not selected['available']: raise ValueError('DST Docker is already on this or a newer version.')
            if (request['tag'], request['commit']) != (selected['tag'], selected['commit']):
                raise ValueError('The latest release changed. Check again and review the new version.')
            identifier = uuid.uuid4().hex
            self.manager('portal-update.reserve', identifier)
            self.operation = {'id': identifier, 'phase': 'running', 'toVersion': selected['latestVersion'],
                              'message': 'Downloading and building DST Docker. The portal will reconnect.', 'startedAt': time.time()}
            atomic(self.directory / 'operation.json', self.operation)
            threading.Thread(target=self.worker, args=(selected, identifier), daemon=True).start()
            return self.operation.copy()
        except Exception:
            if identifier:
                self.manager('portal-update.release', identifier)
                self.operation = None
            raise
        finally: self.lock.release()

    def worker(self, selected, identifier):
        try:
            env = {**os.environ, 'DST_SELF_UPDATE': '1', 'DST_EXPECTED_RELEASE_TAG': selected['tag'],
                   'DST_EXPECTED_RELEASE_COMMIT': selected['commit']}
            with (self.directory / 'update.log').open('w', encoding='utf-8') as log:
                (self.directory / 'update.log').chmod(0o600)
                result = subprocess.run(['bash', str(self.source() / 'bootstrap.sh'), '--prefix', str(self.root),
                                         '--non-interactive'], env=env, stdin=subprocess.DEVNULL,
                                        stdout=log, stderr=subprocess.STDOUT, timeout=7200)
            if result.returncode or self.current() != selected['latestVersion']:
                raise ValueError('The update did not finish. Your data was kept. Check the update log and retry.')
            self.record(phase='completed', message='DST Docker updated successfully. Reload the portal.', finishedAt=time.time())
        except Exception:
            self.record(phase='failed', message='The update did not finish. Your data was kept. Check the update log and retry.', finishedAt=time.time())
        finally:
            try: self.manager('portal-update.release', identifier)
            except Exception:
                self.record(phase='failed', message='Check the portal and restart the DST update service to release its maintenance lock.')
        if self.operation and self.operation['phase'] == 'completed':
            # Load the updated helper as well as the updated portal. Socket
            # clients reconnect; the registered service keeps the same PID.
            os.execv(sys.executable, [sys.executable, str(self.source() / 'packaging/docker/portal_update.py'),
                                     'serve', '--root', str(self.root)])

    def request(self, request):
        action = request.get('action')
        if action == 'install': return self.install(request)
        if action != 'status' or set(request) - {'action', 'force'} or type(request.get('force', False)) is not bool:
            raise ValueError('Choose a supported DST update action.')
        try: result = self.check(request.get('force', False))
        except Exception:
            result = {'currentVersion': self.current(), 'available': False,
                      'error': 'Could not check GitHub for updates. Check the host internet connection and try again.'}
        with self.lock: return {**result, 'supported': True, 'operation': self.operation}

    def serve(self):
        if self.operation and self.operation['phase'] == 'running':
            self.manager('portal-update.release', self.operation['id'])
            self.record(phase='failed', message='The host restarted during the update. Check DST and retry.')
        path = self.directory / 'update.sock'
        path.unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(path)); path.chmod(0o666); server.listen(5)
            while True:
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(60)
                    try:
                        _, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                        if uid not in {0, os.getuid(), 10001}: raise ValueError('DST update access denied.')
                        with connection.makefile('rb') as stream: raw = stream.readline(4097)
                        if len(raw) > 4096: raise ValueError('Update request is too large.')
                        response = {'ok': True, 'data': self.request(json.loads(raw))}
                    except Exception as error:
                        response = {'ok': False, 'error': str(error) if isinstance(error, ValueError) else 'DST update service is unavailable.'}
                    try: connection.sendall(json.dumps(response).encode() + b'\n')
                    except OSError: pass


def prepare(root):
    root = Path(root).resolve()
    directory = root / 'portal-update'
    if directory.is_symlink(): raise ValueError('The update directory must not be a symbolic link.')
    directory.mkdir(exist_ok=True); directory.chmod(0o755)
    owner = root.stat()
    if os.geteuid() == 0:
        os.chown(directory, owner.st_uid, owner.st_gid, follow_symlinks=False)
        for name in ('operation.json', 'update.log'):
            path = directory / name
            if path.is_symlink(): raise ValueError('The update files must not be symbolic links.')
            if path.exists(): os.chown(path, owner.st_uid, owner.st_gid, follow_symlinks=False)
    atomic(root / 'update.compose.json', {'services': {'dst': {'volumes': [
        {'type': 'bind', 'source': str(directory), 'target': '/update-control', 'read_only': True}]}}})
    if os.geteuid() == 0: os.chown(root / 'update.compose.json', owner.st_uid, owner.st_gid, follow_symlinks=False)


def register(root):
    import pwd
    root = Path(root).resolve()
    account = pwd.getpwuid(root.stat().st_uid)
    unit = 'dst-docker-update-' + hashlib.sha256(str(root).encode()).hexdigest()[:16] + '.service'
    def quoted(value):
        if '\n' in str(value) or '\r' in str(value): raise ValueError('Unsupported installation path.')
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
    content = ('[Unit]\nDescription=DST Docker product updater\nAfter=docker.service network-online.target\n'
               '[Service]\nType=simple\nUser=' + account.pw_name + '\nSupplementaryGroups=docker\nUMask=0077\n'
               'Environment=' + quoted('HOME=' + account.pw_dir) + '\n' +
               ('Environment=' + quoted('WSL_DISTRO_NAME=' + os.environ['WSL_DISTRO_NAME']) + '\n' if os.environ.get('WSL_DISTRO_NAME') else '') +
               'ExecStart=' + quoted(sys.executable) + ' ' + quoted(root / 'current/packaging/docker/portal_update.py') +
               ' serve --root ' + quoted(root) + '\nRestart=on-failure\nRestartSec=5\n[Install]\nWantedBy=multi-user.target\n')
    (Path('/etc/systemd/system') / unit).write_text(content)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', unit], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'register', 'serve']); parser.add_argument('--root', required=True)
    args = parser.parse_args()
    if args.action == 'prepare': prepare(args.root)
    elif args.action == 'register': register(args.root)
    else: Updater(args.root).serve()
