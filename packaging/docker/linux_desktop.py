"""Register and open a per-user desktop entry for a native Linux installation."""

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit


PORT_FILE = 'desktop-portal.port'
SCRIPT = 'packaging/docker/linux_desktop.py'


def atomic_text(path, value, mode):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as temporary:
        staged = Path(temporary.name)
        try:
            temporary.write(value)
            temporary.flush()
            os.fchmod(temporary.fileno(), mode)
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)


def remember_port(path, url):
    port = urlsplit(url).port
    if port is None or not 1024 <= port <= 65535:
        raise ValueError('The portal has an invalid console port.')
    value = f'{port}\n'
    if not path.is_file() or path.read_text(encoding='utf-8') != value:
        atomic_text(path, value, 0o644)


def portal_address(root):
    https = root / 'https.compose.json'
    if https.is_file():
        origin = urlsplit(json.loads(https.read_text(encoding='utf-8'))['x-dst-https-origin'])
        if (origin.scheme != 'https' or not origin.hostname or origin.username or origin.path
                or origin.query or origin.fragment or not origin.port or origin.port < 1024):
            raise ValueError('The portal has an invalid HTTPS address.')
        host = ipaddress.IPv4Address(origin.hostname)
        return f'https://{host}:{origin.port}/'
    port = int((root / PORT_FILE).read_text(encoding='utf-8').strip())
    if not 1024 <= port <= 65535:
        raise ValueError('The portal has an invalid console port.')
    return f'http://127.0.0.1:{port}/'


def desktop_value(value):
    return value.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')


def exec_argument(value):
    quoted = ''.join('\\' + character if character in '"`$\\' else character for character in value)
    return '"' + desktop_value(quoted.replace('%', '%%')) + '"'


def desktop_entry(root, source):
    launcher = exec_argument(str(source / SCRIPT))
    location = exec_argument(str(root))
    return (
        '[Desktop Entry]\n'
        'Type=Application\n'
        'Name=DST Docker\n'
        'Comment=Open the DST Docker portal\n'
        f'Exec=python3 {launcher} open {location}\n'
        f'Icon={desktop_value(str(source / "webui/public/logo.png"))}\n'
        'Terminal=false\n'
        'Categories=Game;System;\n'
        f'X-DST-Install-Root={desktop_value(str(root))}\n'
    )


def desktop_directory(home):
    lookup = shutil.which('xdg-user-dir')
    path = home / 'Desktop'
    if lookup:
        result = subprocess.run([lookup, 'DESKTOP'], text=True, capture_output=True, timeout=5, check=True)
        path = Path(result.stdout.strip())
    if path.is_absolute() and path.is_dir() and path.resolve() != home.resolve():
        return path
    return None


def save_entry(path, entry, marker, mode):
    if path.is_symlink() or (path.exists() and (
            not path.is_file() or marker not in path.read_text(encoding='utf-8').splitlines())):
        return False
    if not path.exists() or path.read_text(encoding='utf-8') != entry or path.stat().st_mode & 0o777 != mode:
        atomic_text(path, entry, mode)
    return True


def register(root, source):
    if not shutil.which('xdg-open') or not (root / PORT_FILE).is_file():
        return []
    home = Path.home()
    desktop = desktop_directory(home)
    if desktop is None and not any(os.environ.get(key) for key in ('DISPLAY', 'WAYLAND_DISPLAY')):
        return []
    data_home = Path(os.environ.get('XDG_DATA_HOME', ''))
    applications = (data_home if data_home.is_absolute() else home / '.local/share') / 'applications'
    applications.mkdir(parents=True, exist_ok=True)
    entry = desktop_entry(root, source)
    marker = 'X-DST-Install-Root=' + desktop_value(str(root))
    suffix = hashlib.sha256(os.fsencode(root)).hexdigest()[:12]
    menu_path = applications / f'dst-docker-{suffix}.desktop'
    saved = [menu_path] if save_entry(menu_path, entry, marker, 0o644) else []
    if desktop:
        for name in ('DST Docker.desktop', f'DST Docker ({suffix}).desktop'):
            path = desktop / name
            if save_entry(path, entry, marker, 0o755):
                saved.append(path)
                break
    return saved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['register', 'open'])
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if os.environ.get('WSL_DISTRO_NAME'):
        return
    if args.action == 'open':
        subprocess.run(['xdg-open', portal_address(root)], check=True)
        return
    if os.geteuid() == 0:
        owner = pwd.getpwuid(root.stat().st_uid)
        if owner.pw_uid == 0:
            return
        # The browser updater runs as root. Resolve the shortcut as the user
        # who owns the installation and create only that user's entries.
        env = {'HOME': owner.pw_dir, 'USER': owner.pw_name, 'LOGNAME': owner.pw_name,
               'PATH': os.defpath}
        subprocess.run([sys.executable, __file__, 'register', str(root)], env=env,
                       user=owner.pw_uid, group=owner.pw_gid, extra_groups=[], check=True)
        return
    source = root / 'current' if (root / 'current' / SCRIPT).is_file() else root
    for path in register(root, source):
        print(f'DST Docker shortcut: {path}')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        sys.exit('DST desktop shortcut: ' + str(error))
