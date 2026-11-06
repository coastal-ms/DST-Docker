import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import assets


class AssetStagingTests(unittest.TestCase):
    def test_download_stage_keeps_the_entire_active_tree_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);active=root/'server';active.mkdir()
            (active/'keep.ini').write_bytes(b'authoritative manual config')
            (root/'install-state.json').write_text('{"state":"downloaded","existing":true}')
            stage=root/'staged'/('a'*32)
            def download(command, **kwargs):
                self.assertIn(str(stage/'server'),command)
                manifest=stage/'server/steamapps/appmanifest_4754530.acf'
                manifest.parent.mkdir(parents=True)
                manifest.write_text('"appid" "4754530"\n"buildid" "120"\n')
                return Mock(returncode=0)
            (stage/'steam').mkdir(parents=True);(stage/'steam/steamcmd.sh').write_text('fixture')
            with patch.object(assets,'package_inventory',return_value=[{'archive':'verified'}]),patch.object(assets.subprocess,'run',side_effect=download):
                assets.install(stage,expected_build='120')
            self.assertEqual((active/'keep.ini').read_bytes(),b'authoritative manual config')
            self.assertEqual(json.loads((root/'install-state.json').read_text()),{'state':'downloaded','existing':True})
            self.assertEqual(json.loads((stage/'install-state.json').read_text())['installedBuild'],'120')

    def test_mismatched_build_fails_only_the_staged_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            stage=Path(folder)/'stage';(stage/'steam').mkdir(parents=True)
            (stage/'steam/steamcmd.sh').write_text('fixture')
            manifest=stage/'server/steamapps/appmanifest_4754530.acf';manifest.parent.mkdir(parents=True)
            manifest.write_text('"appid" "4754530"\n"buildid" "121"\n')
            with patch.object(assets,'package_inventory',return_value=[]),patch.object(assets.subprocess,'run',return_value=Mock(returncode=0)):
                with self.assertRaisesRegex(ValueError,'different build'): assets.install(stage,expected_build='120')
            self.assertEqual(json.loads((stage/'install-state.json').read_text())['state'],'failed')

    def test_stage_identity_is_validated_before_any_installer_write(self):
        for stage,build in [('../active','120'),('a'*32,'invalid'),('', '120')]:
            with patch.dict(os.environ,{'DST_ASSETS_STAGE_ID':stage,'DST_EXPECTED_BUILD':build}),patch.object(assets,'install') as install:
                with self.assertRaises(ValueError):assets.main()
                install.assert_not_called()
