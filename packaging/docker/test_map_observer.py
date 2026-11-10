import base64
import importlib.util
import json
import os
from pathlib import Path
import shlex
import socket
import tempfile
import threading
import unittest

spec=importlib.util.spec_from_file_location('map_observer',Path(__file__).with_name('map-observer.py'))
observer=importlib.util.module_from_spec(spec);spec.loader.exec_module(observer)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.path=self.root/'observer.sock';self.server=observer.Server(str(self.path),observer.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.temporary.cleanup()
    def request(self,request):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.connect(str(self.path));connection.sendall(json.dumps(request).encode()+b'\n')
            return json.loads(connection.makefile('rb').readline())
    def test_binary_observation_round_trips_without_text_conversion(self):
        payload=b'\x00\xff\r\n'+bytes(range(256))
        result=self.request({'command':'cat','input':base64.b64encode(payload).decode(),'timeout':5})
        self.assertTrue(result['ok']);self.assertEqual(base64.b64decode(result['output']),payload)
    def test_invalid_timeouts_never_execute_the_command(self):
        path=self.root/'should-not-exist'
        result=self.request({'command':'touch '+shlex.quote(str(path)),'timeout':301})
        self.assertFalse(result['ok']);self.assertFalse(path.exists())
    def test_timeout_terminates_the_whole_observer_process_group(self):
        path=self.root/'child.pid'
        result=self.request({'command':'sleep 30 & echo $! > '+shlex.quote(str(path))+'; wait','timeout':1})
        self.assertFalse(result['ok']);pid=int(path.read_text())
        try:state=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[0]
        except FileNotFoundError:state=None
        self.assertIn(state,(None,'Z'))


if __name__=='__main__':unittest.main()
