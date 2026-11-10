from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import update_progress as progress


class UpdateProgressTests(unittest.TestCase):
    def state(self):
        return {'id': 'a'*32, 'operation': {'id': 'b'*32, 'action': 'updates.apply', 'phase': 'running'},
                'updateRun': {'id': 'b'*32, 'phase': 'staging', 'build': '123', 'startedAt': 10},
                'assetUpdate': {'id': 'c'*32, 'expectedBuild': '123', 'startedAt': 11}}

    def test_summary_works_during_updates_and_does_not_read_output(self):
        engine=Mock();s=self.state()
        row=progress.snapshot(s,engine)
        self.assertTrue(row['running']);self.assertEqual(row['label'],'Downloading update')
        self.assertEqual(row['output'],[]);engine.iter_logs.assert_not_called()

    def test_reopen_shows_latest_completed_update_after_an_unrelated_operation(self):
        s=self.state();s['updateRun']['phase']='completed';s['operation']={'id':'d'*32,'action':'backups.create','phase':'running'}
        row=progress.snapshot(s,Mock())
        self.assertFalse(row['running']);self.assertEqual(row['status'],'completed')
        self.assertEqual(row['operationId'],'b'*32)

    def test_rejects_foreign_operation_and_invalid_options_before_reading(self):
        for identifier in ['d'*32,'../config','',123]:
            with self.assertRaises(ValueError):progress.snapshot(self.state(),Mock(),identifier,True)
        with self.assertRaises(ValueError):progress.snapshot(self.state(),Mock(),include_output='1')
        self.assertEqual(progress.snapshot({},Mock()),{'available':False})

    def test_redacts_steam_and_owned_job_output_and_preserves_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);stage=root/'staged'/('c'*32);stage.mkdir(parents=True)
            (stage/'steam-install.log').write_text('\x1b[0mDownloading 75%\npassword=private\n')
            s=self.state();s['updateRun'].update(phase='failed-preflight',error='password=hidden',backupId='saved')
            s['operation']['phase']='failed';s['backups']={'saved':{'job':'owned'}}
            engine=Mock();engine.iter_logs.return_value=iter([b'postgres://user:secret@database\n'])
            row=progress.snapshot(s,engine,include_output=True,assets=root)
            self.assertEqual(row['status'],'failed');self.assertNotIn('hidden',row['error'])
            self.assertIn('75%',row['output'][0]['text']);self.assertNotIn('private',row['output'][0]['text'])
            self.assertNotIn('\x1b',row['output'][0]['text']);self.assertNotIn('secret',row['output'][1]['text'])
            engine.iter_logs.assert_called_once_with('owned',{'io.dst.managed':'true','io.dst.project':'a'*32,'io.dst.component':'db-backup'},tail=200,max_bytes=progress.LIMIT)

    def test_does_not_read_old_or_unrelated_downloads(self):
        s=self.state();s['assetUpdate']['startedAt']=9
        row=progress.snapshot(s,Mock(),include_output=True)
        self.assertEqual(row['output'],[])

    def test_tail_is_bounded_and_discards_partial_first_line(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'log';p.write_bytes(b'x'*(progress.LIMIT+100)+b'\nLatest output\n')
            text,truncated=progress.file_tail(p)
            self.assertTrue(truncated);self.assertEqual(text,'Latest output\n')

    def test_a_missing_retained_job_is_reported_without_failing_other_details(self):
        s=self.state();s['updateRun']['migrationJob']='missing'
        engine=Mock();engine.iter_logs.side_effect=ValueError('foreign or deleted')
        row=progress.snapshot(s,engine,include_output=True)
        self.assertIn('unavailable',row['output'][-1]['error'])


if __name__=='__main__':unittest.main()
