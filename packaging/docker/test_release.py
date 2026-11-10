import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from build_release import build

class DockerReleaseTests(unittest.TestCase):
    def test_release_payload_checksum_version_and_source_are_bound_to_committed_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'source';root.mkdir()
            def git(*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.DEVNULL,text=True).strip()
            git('init');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
            (root/'packaging/docker').mkdir(parents=True);(root/'webui').mkdir();(root/'bin').mkdir()
            identity={'name':'DST Docker','version':'1.0.0','repository':'coastal-ms/DST-Docker','tag':'v1.0.0','distribution':'source','bootstrap':'bootstrap.sh'}
            (root/'packaging/docker/release.json').write_text(json.dumps(identity))
            (root/'webui/package.json').write_text('{"version":"1.0.0"}')
            (root/'CHANGELOG.md').write_text('# Changes\n\n## [1.0.0]\n\n- Host servers in Docker.\n')
            (root/'bin/dst-install').write_text('#!/bin/bash\n# DST_EMBEDDED_SOURCE\n')
            git('add','.');git('commit','-m','Release fixture');revision=git('rev-parse','HEAD')
            # An uncommitted template must never get into the release artifact.
            (root/'bin/dst-install').write_text('uncommitted-template')
            output=Path(temporary)/'assets';manifest=build(root,revision,output)
            self.assertEqual(manifest['uploadedAssets'],[])
            self.assertFalse((output/'dst-docker-install.sh').exists())
            self.assertFalse((output/'SHA256SUMS').exists())
            self.assertEqual(manifest['repository'],'coastal-ms/DST-Docker')
            self.assertIn('/DST-Docker/main/bootstrap.sh',(output/'install-command.txt').read_text())
            self.assertEqual(manifest['sourceCommit'],revision)

if __name__=='__main__':unittest.main()
