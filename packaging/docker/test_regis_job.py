from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import regis_job


class RegisJobTests(unittest.TestCase):
    def test_all_shipped_recipes_are_supported_with_fixed_tank_asset_paths(self):
        root = Path(__file__).parents[2] / 'app/resources/regis-tanks'
        for build in regis_job.BUILDS:
            with self.subTest(build=build):
                regis_job.validate_recipe(json.loads((root / (build + '.json')).read_text()), build)

    def test_recipe_rejects_foreign_asset_paths_bool_offsets_bad_hex_and_overlap(self):
        root = Path(__file__).parents[2] / 'app/resources/regis-tanks/2173753.json'
        original = json.loads(root.read_text())
        for mutation in ('path', 'bool', 'hex', 'length', 'overlap', 'schema'):
            recipe = deepcopy(original)
            if mutation == 'path': recipe['stockFiles']['../Saved/UserGame.ini'] = 'a' * 64
            if mutation == 'bool': recipe['sites'][0][0] = True
            if mutation == 'hex': recipe['sites'][0][1] = 'xx'
            if mutation == 'length': recipe['sites'][0][2] += '90'
            if mutation == 'overlap': recipe['sites'].append(recipe['sites'][0])
            if mutation == 'schema': recipe['schema'] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                regis_job.validate_recipe(recipe, '2173753')

    def test_binary_patch_checks_source_each_site_and_complete_output_without_changing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'source'; output = root / 'new'
            source.write_bytes(b'0123456789')
            recipe = {'cleanExecutableSha256': hashlib.sha256(b'0123456789').hexdigest(),
                      'patchedExecutableSha256': hashlib.sha256(b'012AB56789').hexdigest(),
                      'sites': [[3, b'34'.hex(), b'AB'.hex()]]}
            regis_job.patch_binary(source, output, recipe)
            self.assertEqual(output.read_bytes(), b'012AB56789')
            self.assertEqual(source.read_bytes(), b'0123456789')
            with self.assertRaises(FileExistsError): regis_job.patch_binary(source, output, recipe)

    def test_unknown_binary_and_symlink_fail_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'source'; output = root / 'new'
            source.write_bytes(b'unknown')
            with self.assertRaisesRegex(ValueError, 'does not match'):
                regis_job.patch_binary(source, output, {'cleanExecutableSha256': 'a' * 64})
            self.assertFalse(output.exists())
            link = root / 'link'; link.symlink_to(source)
            with self.assertRaisesRegex(ValueError, 'symbolic link'):
                regis_job.digest(link)

    def test_bad_site_or_complete_hash_cannot_be_reported_as_a_success(self):
        for site, expected in (([2, 'ff', 'aa'], hashlib.sha256(b'abc').hexdigest()),
                               ([2, b'c'.hex(), b'd'.hex()], 'a' * 64)):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory); source = root / 'source'; source.write_bytes(b'abc')
                with self.assertRaises(ValueError):
                    regis_job.patch_binary(source, root / 'new', {'cleanExecutableSha256': hashlib.sha256(b'abc').hexdigest(),
                        'patchedExecutableSha256': expected, 'sites': [site]})
                self.assertEqual(source.read_bytes(), b'abc')
                self.assertFalse((root / 'report.json').exists())


if __name__ == '__main__': unittest.main()
