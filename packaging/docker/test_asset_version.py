from pathlib import Path
import tempfile
import unittest
from asset_version import installed_version


class AssetVersionTests(unittest.TestCase):
    def test_reads_only_version_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / 'manifest'
            manifest.write_text('"AppState"\n{\n "appid" "4754530"\n "buildid" "12345678"\n "irrelevant" "not returned"\n}\n')
            self.assertEqual(installed_version(manifest), {'appId':'4754530', 'installedBuild':'12345678'})

    def test_rejects_ambiguous_wrong_or_missing_version(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / 'manifest'
            for text in ('"appid" "12"\n"buildid" "44"', '"appid" "4754530"',
                         '"appid" "4754530"\n"buildid" "44"\n"buildid" "45"',
                         '"appid" "4754530"\n"buildid" "0"'):
                manifest.write_text(text)
                with self.assertRaises(ValueError): installed_version(manifest)

    def test_rejects_oversize_or_missing_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / 'manifest'
            with self.assertRaises(ValueError): installed_version(manifest)
            manifest.write_bytes(b'x' * (1024 * 1024 + 1))
            with self.assertRaises(ValueError): installed_version(manifest)
