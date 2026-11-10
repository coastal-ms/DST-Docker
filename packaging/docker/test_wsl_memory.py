import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import wsl_memory as memory

class WslMemoryTests(unittest.TestCase):
    def test_preserves_other_sections_comments_case_and_crlf(self):
        original=b'# keep\r\n[wsl2]\r\nprocessors=8\r\n Memory = 40960MB # ceiling\r\nswap=10GB\r\n[experimental]\r\nautoMemoryReclaim=gradual\r\n'
        updated=memory.update_config(original,24)
        self.assertEqual(updated,original.replace(b'40960MB',b'24GB'))
        self.assertEqual(memory.memory_gib(memory.memory_value(memory.decode(updated)[0])),24)
    def test_new_file_existing_section_and_no_trailing_newline(self):
        self.assertEqual(memory.update_config(b'',20),b'[wsl2]\nmemory=20GB\n')
        self.assertEqual(memory.update_config(b'[wsl2]\nprocessors=8',20),b'[wsl2]\nprocessors=8\nmemory=20GB\n')
        self.assertEqual(memory.update_config(b'[wsl2]\nprocessors=8\n[experimental]\nfoo=bar\n',20),b'[wsl2]\nprocessors=8\nmemory=20GB\n[experimental]\nfoo=bar\n')
    def test_default_removes_only_wsl_memory_including_duplicate_keys(self):
        original=b'[wsl2]\nmemory=40GB\nprocessors=8\nMEMORY=32GB\n[other]\nmemory=keep\n'
        self.assertEqual(memory.update_config(original,None),b'[wsl2]\nprocessors=8\n[other]\nmemory=keep\n')
        self.assertEqual(memory.update_config(b'',None),b'')
    def test_preserves_utf16_and_utf8_bom_and_legacy_comments(self):
        for encoding,bom in [('utf-16-le',b'\xff\xfe'),('utf-16-be',b'\xfe\xff'),('utf-8',b'\xef\xbb\xbf'),('cp1252',b'')]:
            with self.subTest(encoding=encoding):
                text='; café\n[wsl2]\nmemory=40GB\n'
                self.assertEqual(memory.update_config(bom+text.encode(encoding),24),bom+text.replace('40GB','24GB').encode(encoding))
    def test_validates_before_writing_and_tracks_pending_until_new_boot(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder);raw=b'[wsl2]\nprocessors=8\n'
            def read(content):return json.dumps({'content':base64.b64encode(content).decode(),'physicalBytes':80*memory.GIB})
            for invalid in [0,-1,81,True,2.5,'24','read',{}]:
                call=Mock(return_value=read(raw))
                with self.subTest(invalid=invalid):
                    with self.assertRaises(ValueError):memory.settings(call,directory,40*memory.GIB,'first',invalid)
                    self.assertEqual(call.call_count,1)
            call=Mock(side_effect=[read(raw),'saved'])
            result=memory.settings(call,directory,40*memory.GIB,'first',24)
            self.assertEqual(result['configuredGiB'],24);self.assertTrue(result['restartRequired'])
            self.assertEqual(result['currentMemoryGiB'],40)
            updated=memory.update_config(raw,24)
            result=memory.settings(Mock(return_value=read(updated)),directory,40*memory.GIB,'first')
            self.assertTrue(result['restartRequired'])
            result=memory.settings(Mock(return_value=read(updated)),directory,24*memory.GIB,'second')
            self.assertFalse(result['restartRequired'])
    def test_failed_write_is_not_recorded_as_success(self):
        with tempfile.TemporaryDirectory() as folder:
            call=Mock(side_effect=[json.dumps({'content':'','physicalBytes':80*memory.GIB}),'failed'])
            with self.assertRaises(ValueError):memory.settings(call,Path(folder),40*memory.GIB,'boot',24)
            self.assertFalse((Path(folder)/'wsl-memory-pending.json').exists())
    def test_sizes_and_write_script_only_uses_fixed_path_and_compares_previous_bytes(self):
        self.assertEqual(memory.memory_gib('24576MB'),24)
        self.assertIsNone(memory.memory_gib('invalid'))
        script=memory.write_script(b'original',b'updated')
        self.assertIn(memory.WINDOWS_PATH,script)
        self.assertIn(base64.b64encode(b'original').decode(),script)
        self.assertIn('[IO.File]::Replace',script)
        self.assertIn('Refresh and save again',script)

if __name__=='__main__':unittest.main()
