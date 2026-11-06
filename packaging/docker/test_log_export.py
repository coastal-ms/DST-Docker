import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import log_export
from engine import Engine, EngineError


class Logs:
    def __init__(self, fail=()): self.calls=[];self.fail=fail
    def iter_logs(self, identifier, labels):
        self.calls.append((identifier, labels))
        if identifier in self.fail: raise EngineError('private diagnostic is not public')
        yield b'World ready\npassword=fixture-secret\neyJheader.'
        yield b'claims.signature\nhttp://localhost/?t=launcher-token\n'


class LogExportTests(unittest.TestCase):
    def state(self): return {'id':'a'*32,'database':{'id':'database'},'services':{'game-1':{'id':'game'}}}

    def test_streams_owned_sources_redacts_across_frames_and_retains_only_three_archives(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);engine=Logs()
            for digit in '1234': result=log_export.export_logs(self.state(),engine,'battlegroup',digit*32,root)
            self.assertTrue(result['complete']);self.assertEqual(result['sources'],2)
            self.assertEqual(len(list(root.glob('*.zip'))),3)
            with zipfile.ZipFile(root/('4'*32+'.zip')) as archive:
                self.assertEqual(set(archive.namelist()),{'postgres.log','game-1.log','export-report.json'})
                raw=archive.read('game-1.log')
                self.assertIn(b'World ready',raw)
                for secret in (b'fixture-secret',b'eyJheader',b'launcher-token'): self.assertNotIn(secret,raw)
            self.assertEqual(engine.calls[0][1]['io.dst.project'],'a'*32)

    def test_reports_partial_collection_and_never_claims_failed_sources_were_captured(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            result=log_export.export_logs(self.state(),Logs(fail={'game'}),'battlegroup','b'*32,root)
            self.assertFalse(result['complete']);self.assertEqual(result['unavailable'],1)
            with zipfile.ZipFile(root/('b'*32+'.zip')) as archive:
                report=json.loads(archive.read('export-report.json'))
                self.assertFalse(report['sources'][1]['ok'])
                self.assertNotIn('private diagnostic',json.dumps(report))

    def test_all_failures_or_invalid_scope_do_not_publish_an_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with self.assertRaises(ValueError): log_export.export_logs(self.state(),Logs(fail={'database','game'}),'battlegroup','b'*32,root)
            with self.assertRaises(ValueError): log_export.export_logs(self.state(),Logs(),'other','b'*32,root)
            with self.assertRaises(ValueError): log_export.export_logs(self.state(),Logs(),'operator','../outside',root)
            self.assertEqual(list(root.iterdir()),[])

    def test_operator_sources_use_the_manager_compose_identity_and_exact_helper_components(self):
        class Operator:
            def inspect(self, identifier): return {'Config':{'Labels':{'com.docker.compose.project':'own-stack','com.docker.compose.service':'manager'}}}
            def request(self, method, path):
                self.path=path
                return [{'Id':'app','Labels':{'com.docker.compose.service':'dst'}},{'Id':'previous-app','Labels':{'com.docker.compose.service':'dst'}},{'Id':'unrelated','Labels':{'com.docker.compose.service':'other'}}]
        engine=Operator();state=self.state()
        state.update(settingsService={'id':'settings'},fileBrowser={'id':'browser'},mapObservers={'game-1':{'id':'map-reader'}})
        with patch.dict(os.environ,{'HOSTNAME':'self'}): selected=log_export.targets(state,engine,'operator')
        self.assertEqual({row[0] for row in selected},{'portal-dst-1','portal-dst-2','settings','file-browser','map-observer-1'})
        self.assertIn('own-stack',engine.path)

    def test_log_stream_checks_ownership_and_rejects_incomplete_frames(self):
        class Client(Engine):
            def inspect(self, identifier): return {'Config':{'Labels':{'project':'owned'}}}
        with self.assertRaises(EngineError): list(Client().iter_logs('container',{'project':'foreign'}))
        class Connection:
            closed=False
            def request(self,*args): pass
            def getresponse(self):
                stream=io.BytesIO(b'\x01\0\0\0\0\0\0\x03abc\x01\0')
                stream.status=200
                return stream
            def close(self): self.closed=True
        connection=Connection()
        with patch('engine.EngineConnection',return_value=connection):
            stream=Client().iter_logs('container',{'project':'owned'})
            self.assertEqual(next(stream),b'abc')
            with self.assertRaises(EngineError):next(stream)
        self.assertTrue(connection.closed)
