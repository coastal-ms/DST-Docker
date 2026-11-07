import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import regis_artifacts as regis

RECIPES = Path(__file__).parents[2] / 'app/resources/regis-tanks'


class RegisArtifactTests(unittest.TestCase):
    def test_absent_oci_runtime_fields_explicitly_clear_preparation_defaults(self):
        base = {'Config': {'Cmd': ['/home/dune/run.sh'], 'Env': ['PATH=/usr/bin'], 'Labels': {'source': 'official'}}}
        config = regis.official_layer_config(base)
        self.assertIn('User', config); self.assertIsNone(config['User'])
        self.assertIn('Entrypoint', config); self.assertIsNone(config['Entrypoint'])
        self.assertIn('Healthcheck', config); self.assertIsNone(config['Healthcheck'])
        self.assertEqual(config['Cmd'], ['/home/dune/run.sh'])
        self.assertNotIn('Labels', config)
        config['Env'].append('UNEXPECTED=1')
        self.assertEqual(base['Config']['Env'], ['PATH=/usr/bin'])

    def setUp(self):
        self.project = 'a' * 32
        self.official = 'registry.funcom.com/funcom/self-hosting/seabass-server:2173753-0-shipping'
        self.recipe = json.loads((RECIPES / '2173753.json').read_text())
        self.base = {'Id': 'sha256:' + 'b' * 64, 'Architecture': 'amd64', 'Os': 'linux',
                     'RepoDigests': ['registry.funcom.com/funcom/self-hosting/seabass-server@' + self.recipe['baseDigest']],
                     'RootFS': {'Layers': ['base-layer']},
                     'Config': {'User': 'dune', 'Entrypoint': ['/official'], 'Cmd': [], 'Env': ['PATH=/usr/bin'], 'WorkingDir': '/home/dune/server'}}

    def test_rejects_unknown_image_and_changed_official_digest_before_accepting_any_artifact(self):
        engine = Mock(); engine.request.return_value = self.base
        with self.assertRaises(ValueError): regis.accepted_source(engine, 'other/server:2173753', RECIPES)
        engine.request.assert_not_called()
        self.base['RepoDigests'] = ['other@sha256:' + 'c' * 64]
        with self.assertRaisesRegex(ValueError, 'official image identity'):
            regis.accepted_source(engine, self.official, RECIPES)

    def test_owned_image_requires_same_project_official_layers_and_original_runtime_config(self):
        image = copy.deepcopy(self.base); image['Id'] = 'sha256:' + 'd' * 64; image['RootFS']['Layers'].append('tank-layer')
        image['Config']['Labels'] = {'io.dst.managed': 'true', 'io.dst.project': self.project, 'io.dst.component': 'regis-image',
            'io.dst.regis.base': self.base['Id'], 'io.dst.regis.build': '2173753', 'io.dst.regis.binary': self.recipe['patchedExecutableSha256']}
        for mutation in ('none', 'project', 'layers', 'env', 'entrypoint', 'volume'):
            candidate = copy.deepcopy(image)
            if mutation == 'project': candidate['Config']['Labels']['io.dst.project'] = 'f' * 32
            if mutation == 'layers': candidate['RootFS']['Layers'][0] = 'foreign-layer'
            if mutation == 'env': candidate['Config']['Env'].append('HOST_SECRET=unexpected')
            if mutation == 'entrypoint': candidate['Config']['Entrypoint'] = ['/unexpected']
            if mutation == 'volume': candidate['Config']['Volumes'] = {'/Saved': {}}
            engine = Mock(); engine.request.side_effect = [self.base, candidate]
            with self.subTest(mutation=mutation):
                if mutation == 'none':
                    self.assertEqual(regis.inspect_compatibility_image(engine, self.project, self.official, image['Id'], RECIPES)['Id'], image['Id'])
                else:
                    with self.assertRaises(ValueError): regis.inspect_compatibility_image(engine, self.project, self.official, image['Id'], RECIPES)

    def test_report_cannot_choose_paths_or_claim_wrong_bytes_and_digests(self):
        expected = {'DuneSandboxServer-Linux-Shipping': self.recipe['patchedExecutableSha256']}
        expected.update({regis.OVERLAY + '.' + ext: sha for ext, sha in regis.OVERLAY_HASHES.items()})
        for mutation in ('extra-path', 'bool-bytes', 'symlink', 'wrong-digest'):
            with tempfile.TemporaryDirectory() as directory, self.subTest(mutation=mutation):
                work = Path(directory); output = work / 'output'; output.mkdir()
                files = {name: {'sha256': sha, 'bytes': 3} for name, sha in expected.items()}
                binary = output / 'DuneSandboxServer-Linux-Shipping'; binary.write_bytes(b'bad')
                if mutation == 'extra-path': files['../../funcom-token'] = {'sha256': 'a' * 64, 'bytes': 3}
                if mutation == 'bool-bytes': files[binary.name]['bytes'] = True
                if mutation == 'symlink': binary.unlink(); binary.symlink_to(work / 'secret')
                (work / 'report.json').write_text(json.dumps({'ok': True, 'build': '2173753', 'files': files}))
                with self.assertRaises(ValueError): regis.checked_report(work, self.recipe)

    def test_report_symlink_and_oversized_json_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory); report = work / 'report.json'
            report.symlink_to(work / 'missing')
            with self.assertRaises(ValueError): regis.checked_report(work, self.recipe)
            report.unlink(); report.write_text(' ' * 32769)
            with self.assertRaises(ValueError): regis.checked_report(work, self.recipe)


if __name__ == '__main__': unittest.main()
