import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import linux_desktop


class LinuxDesktopTests(unittest.TestCase):
    def test_register_updates_only_owned_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            desktop = home / 'Bureau'
            desktop.mkdir()
            root = home / 'DST setup'
            root.mkdir()
            linux_desktop.remember_port(root / linux_desktop.PORT_FILE, 'http://127.0.0.1:9191/?t=private')
            other = desktop / 'DST Docker.desktop'
            other.write_text('Another shortcut', encoding='utf-8')
            with (
                patch.object(Path, 'home', return_value=home),
                patch.object(linux_desktop, 'desktop_directory', return_value=desktop),
                patch.object(linux_desktop.shutil, 'which', return_value='/usr/bin/xdg-open'),
                patch.dict(os.environ, {'XDG_DATA_HOME': str(home / 'application data')}),
            ):
                paths = linux_desktop.register(root, root / 'current')
                self.assertEqual(paths, linux_desktop.register(root, root / 'current'))
            self.assertEqual(len(paths), 2)
            self.assertEqual(other.read_text(encoding='utf-8'), 'Another shortcut')
            self.assertEqual(paths[0].parent, home / 'application data/applications')
            self.assertEqual(paths[1].parent, desktop)
            self.assertEqual(paths[1].stat().st_mode & 0o777, 0o755)
            entry = paths[0].read_text(encoding='utf-8')
            self.assertIn('Terminal=false\n', entry)
            self.assertIn('current/packaging/docker/linux_desktop.py" open "', entry)
            self.assertNotIn('private', entry)

    def test_headless_registration_leaves_the_home_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            linux_desktop.remember_port(root / linux_desktop.PORT_FILE, 'http://127.0.0.1:8088')
            with (
                patch.object(Path, 'home', return_value=root),
                patch.object(linux_desktop, 'desktop_directory', return_value=None),
                patch.object(linux_desktop.shutil, 'which', return_value='/usr/bin/xdg-open'),
                patch.dict(os.environ, {}, clear=True),
            ):
                self.assertEqual(linux_desktop.register(root, root), [])
            self.assertFalse((root / '.local').exists())

    def test_display_records_only_the_public_port_and_open_uses_current_https(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            port_file = root / linux_desktop.PORT_FILE
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name('portal_urls.py')), '--https-origin', 'https://192.168.1.4:9443'],
                input='http://127.0.0.1:18088/?t=fixture', text=True, capture_output=True, check=True,
                env={**os.environ, 'DST_DESKTOP_PORT_FILE': str(port_file)},
            )
            self.assertIn('https://192.168.1.4:9443/?t=fixture', result.stdout)
            self.assertEqual(port_file.read_text(encoding='utf-8'), '9443\n')
            https = root / 'https.compose.json'
            https.write_text(json.dumps({'x-dst-https-origin': 'https://192.168.1.4:9443'}), encoding='utf-8')
            self.assertEqual(linux_desktop.portal_address(root), 'https://192.168.1.4:9443/')
            https.unlink()
            self.assertEqual(linux_desktop.portal_address(root), 'http://127.0.0.1:9443/')
