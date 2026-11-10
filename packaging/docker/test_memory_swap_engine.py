import json
import unittest
from unittest.mock import patch

from engine import Engine
from memory_swap import GIB


class SwapEngine(Engine):
    def __init__(self):
        self.calls=[]
        self.config={'Memory':16*GIB,'MemorySwap':16*GIB}
    def assert_owned(self, identifier, project, component=None):
        if identifier!='owned-map' or project!='a'*32 or component!='game-1':raise ValueError('foreign map')
        return {'HostConfig':self.config.copy(),'State':{'Status':'running'}}
    def inspect(self, identifier):
        return {'Image':'sha256:'+'b'*64}
    def request(self, method, path, body=None, expected=None, timeout=30):
        self.calls.append((method,path,body))
        if path=='/info':return {'SwapLimit':True,'SecurityOptions':[]}
        if '/update' in path:self.config.update(body)
        return {'Id':'helper-id'}


class MemorySwapEngineTests(unittest.TestCase):
    def test_live_allowance_and_disable_preserve_ram_and_update_only_swap(self):
        engine=SwapEngine()
        engine.set_component_swap('owned-map','a'*32,'game-1',{'enabled':True,'perServerGiB':2})
        self.assertEqual(engine.config,{'Memory':16*GIB,'MemorySwap':18*GIB})
        self.assertEqual(engine.calls[-1][2],{'MemorySwap':18*GIB})
        engine.set_component_swap('owned-map','a'*32,'game-1',{'enabled':False})
        self.assertEqual(engine.config,{'Memory':16*GIB,'MemorySwap':32*GIB})

    def test_read_only_status_has_no_privileged_or_writable_host_mount(self):
        engine=SwapEngine()
        with patch.dict('os.environ',{'HOSTNAME':'own-manager'}):
            engine.create_host_swap_job('a'*32,{'action':'status','image':'untrusted','path':'/etc/shadow'})
        body=engine.calls[-1][2]
        self.assertFalse(body['HostConfig']['Privileged'])
        self.assertEqual(body['HostConfig']['NetworkMode'],'none')
        self.assertTrue(body['HostConfig']['Mounts'][0]['ReadOnly'])
        self.assertEqual(body['Image'],'sha256:'+'b'*64)
        self.assertEqual(json.loads(body['Cmd'][0]),{'action':'status','project':'a'*32})

    def test_foreign_map_or_wrong_component_cannot_receive_swap_updates(self):
        engine=SwapEngine()
        for identifier,project,component in [('other','a'*32,'game-1'),('owned-map','c'*32,'game-1'),('owned-map','a'*32,'postgres')]:
            with self.assertRaises(ValueError):engine.set_component_swap(identifier,project,component,{'enabled':False})
        self.assertFalse(engine.calls)


if __name__=='__main__':unittest.main()
