import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / 'bootstrap.sh'
CODE = SOURCE.read_text().split("<<'DST_BOOTSTRAP_PY'\n", 1)[1].rsplit('\nDST_BOOTSTRAP_PY', 1)[0]
module = {'__name__': 'bootstrap_test'}
exec(compile(CODE, str(SOURCE), 'exec'), module)

def archive(name='repo-sha/bin/dst-install', kind=None):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as target:
        item = tarfile.TarInfo(name)
        content = b'#!/bin/bash\nexit 0\n'
        if kind:
            item.type = kind
            item.linkname = '/etc/passwd'
        else: item.size = len(content)
        item.mode = 0o755
        target.addfile(item, io.BytesIO(content) if not kind else None)
    return data.getvalue()

class BootstrapTests(unittest.TestCase):
    def test_github_source_archive_becomes_installer_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / 'source.tar.gz'
            installer = module['normalize'](archive(), dest)
            self.assertIn(b'exit 0', installer)
            with tarfile.open(dest) as source:
                self.assertEqual(source.getnames(), ['bin/dst-install'])
                self.assertEqual(source.getmember('bin/dst-install').mode, 0o755)
            first = dest.read_bytes()
            module['normalize'](archive(), dest)
            self.assertEqual(dest.read_bytes(), first)

    def test_rejects_unsafe_or_truncated_source(self):
        for data in (archive('../bin/dst-install'), archive('/bin/dst-install'), archive(kind=tarfile.SYMTYPE), archive()[:30]):
            with self.subTest(data=data[:10]), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises((ValueError, tarfile.TarError, EOFError)):
                    module['normalize'](data, Path(folder) / 'source.tar.gz')

    def test_latest_tag_is_resolved_to_commit_and_arguments_forwarded(self):
        commit = 'a' * 40
        responses = [json.dumps({'tag_name':'v1.0.0'}).encode(), json.dumps({'object':{'sha':commit,'type':'commit'}}).encode(), archive()]
        with patch.dict(module, download=lambda *args: responses.pop(0), token=lambda: ''):
            with patch('subprocess.call', return_value=0) as call:
                self.assertEqual(module['main'](['--prefix','/tmp/dst-fixture','--non-interactive']), 0)
                args, kwargs = call.call_args
                self.assertEqual(args[0][-3:], ['--prefix','/tmp/dst-fixture','--non-interactive'])
                self.assertEqual(kwargs['env']['task_package_revision'], commit)
                self.assertEqual(kwargs['env']['task_product_version'], '1.0.0')

    def test_redirect_drops_private_credentials_on_another_host(self):
        import urllib.request
        req = urllib.request.Request('https://api.github.com/a', headers={'Authorization':'Bearer fixture'})
        result = module['Redirect']().redirect_request(req,None,302,'',{},'https://codeload.github.com/a')
        self.assertFalse(result.has_header('Authorization'))

if __name__ == '__main__': unittest.main()
