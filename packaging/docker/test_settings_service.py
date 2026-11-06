from pathlib import Path
import hashlib
import os
import tempfile
import unittest
from unittest.mock import patch

from settings_service import SavedSettings,SettingsConflict,authorize_peer,MAX_FILE


class SavedSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.saved=Path(self.directory.name)
        self.root=self.saved/'UserSettings';self.root.mkdir()
        self.file=self.root/'UserGame.ini'
        self.original='\ufeff; operator comment\r\n[Custom]\r\nManual=42\r\n'
        self.file.write_bytes(self.original.encode())
        self.file.chmod(0o640)
        self.store=SavedSettings(self.saved)

    def tearDown(self):self.directory.cleanup()

    def test_round_trip_preserves_exact_bytes_mode_and_verified_before_image(self):
        before=self.store.read('game')
        updated=self.original.replace('42','43')
        result=self.store.write('game',updated,before['revision'],True)
        self.assertEqual(self.file.read_bytes(),updated.encode())
        self.assertEqual((self.root/'.dst-backups'/result['backup']).read_bytes(),self.original.encode())
        self.assertEqual(self.file.stat().st_mode&0o777,0o640)
        self.assertEqual(result['revision'],hashlib.sha256(updated.encode()).hexdigest())
        self.assertTrue(result['changed'])

    def test_external_edit_rejects_stale_save_without_changing_manual_content(self):
        before=self.store.read('game');self.file.write_bytes(b'Manual=99\n')
        with self.assertRaises(SettingsConflict):self.store.write('game','Manual=1',before['revision'],True)
        self.assertEqual(self.file.read_bytes(),b'Manual=99\n')
        self.assertFalse((self.root/'.dst-backups').exists())

    def test_absent_and_empty_files_are_distinct_and_deletion_is_not_resurrected(self):
        self.file.write_bytes(b'');before=self.store.read('game');self.file.unlink()
        with self.assertRaises(SettingsConflict):self.store.write('game','',before['revision'],True)
        self.assertFalse(self.file.exists())
        missing=self.store.read('game')
        created=self.store.write('game','[Manual]\n',missing['revision'],False)
        removed=self.store.write('game','',created['revision'],True,remove=True)
        self.assertFalse(removed['fileExists']);self.assertFalse(self.file.exists())
        self.assertEqual((self.root/'.dst-backups'/removed['backup']).read_bytes(),b'[Manual]\n')

    def test_missing_directory_invalid_ids_symlinks_and_invalid_utf8_fail_closed(self):
        for key in [None,[],{},'../game','UserGame.ini']:
            with self.assertRaises(ValueError):self.store.read(key)
        self.file.unlink();self.file.symlink_to(self.saved/'outside')
        with self.assertRaises(ValueError):self.store.read('game')
        self.file.unlink();self.file.write_bytes(b'\xff')
        with self.assertRaises(UnicodeError):self.store.read('game')
        self.file.unlink();self.root.rmdir()
        with self.assertRaises(ValueError):self.store.read('game')
        self.assertFalse(self.root.exists())

    def test_bounds_noop_backup_symlink_and_external_edit_during_save(self):
        before=self.store.read('game')
        self.assertFalse(self.store.write('game',before['raw'],before['revision'],True)['changed'])
        self.assertFalse((self.root/'.dst-backups').exists())
        with self.assertRaises(ValueError):self.store.write('game','x'*(MAX_FILE+1),before['revision'],True)
        outside=self.saved/'other';outside.mkdir();(self.root/'.dst-backups').symlink_to(outside)
        with self.assertRaises(ValueError):self.store.write('game','new',before['revision'],True)
        (self.root/'.dst-backups').unlink()
        real_mkstemp=tempfile.mkstemp
        def concurrent_edit(*args,**kwargs):
            self.file.write_bytes(b'external edit');return real_mkstemp(*args,**kwargs)
        with patch('settings_service.tempfile.mkstemp',side_effect=concurrent_edit):
            with self.assertRaises(SettingsConflict):self.store.write('game','new',before['revision'],True)
        self.assertEqual(self.file.read_bytes(),b'external edit')
        self.assertEqual(list(self.root.glob('.dst-UserGame.ini-*')),[])

    def test_public_helper_has_no_generic_operations_and_rejects_scaler_identity(self):
        authorize_peer(0);authorize_peer(10001)
        for uid in [1000,10002,65534]:
            with self.assertRaises(ValueError):authorize_peer(uid)
        for request in [[],{'action':'exec'},{'action':'write','file':'game','raw':'x','revision':'0'*64}]:
            with self.assertRaises(ValueError):self.store.dispatch(request)

    def test_backup_management_only_removes_selected_settings_before_images(self):
        (self.root/'UserEngine.ini').write_bytes(b'engine manual\r\n')
        result=self.store.backup_files(['game','engine'])
        self.assertTrue(all(row['ok'] for row in result['files']))
        rows=self.store.backups();self.assertEqual(len(rows),2)
        removed=self.store.delete_backups([rows[0]['path'],'/srv/UserSettings/UserGame.ini','../outside'])
        self.assertEqual(removed['deleted'],1)
        self.assertEqual(len(self.store.backups()),1)
        self.assertEqual(self.file.read_bytes(),self.original.encode())

    def test_backup_failure_does_not_modify_either_source(self):
        engine=self.root/'UserEngine.ini';engine.write_bytes(b'original engine')
        original=self.store.backup_snapshot
        def fail_second(key,before):
            if key=='engine':raise OSError('full disk')
            return original(key,before)
        with patch.object(self.store,'backup_snapshot',side_effect=fail_second):
            with self.assertRaises(OSError):self.store.backup_files(['game','engine'])
        self.assertEqual(self.file.read_bytes(),self.original.encode());self.assertEqual(engine.read_bytes(),b'original engine')


if __name__=='__main__':unittest.main()
