import os
import unittest
from unittest.mock import patch
import mirror_jobs


class FakeEngine:
    def __init__(self):
        self.original=None
        self.fallback={'Id':'sha256:new','Config':{'Labels':{'io.dst.backup-mirror-helper':'1'}}}
        self.created=[];self.reads=[]
    def inspect(self, identifier):
        return {'Image':'sha256:old','Config':{'Labels':{'com.docker.compose.project':'fixture'}},
                'Mounts':[{'Type':'bind','Source':'/home/test/backups','Destination':'/mirror','RW':True}]}
    def request(self,method,path,body=None,expected=None):
        if method=='POST':self.created.append(body);return {'Id':'new-job'}
        self.reads.append(path)
        if path.startswith('/volumes/'):
            return {'Labels':{'io.dst.managed':'true','io.dst.project':'a'*32}}
        if path=='/images/sha256%3Aold/json':return self.original
        if path=='/images/dst-docker-manager%3Alocal/json':return self.fallback
        if path.startswith('/containers/'):return None
        raise AssertionError(path)


class MirrorImageTests(unittest.TestCase):
    def setUp(self):
        self.engine=FakeEngine()
        self.request={'id':'b'*32,'attempt':0,'files':[{'name':'backup-123-abcdef12.dump','bytes':12,'sha256':'c'*64}]}
    def create(self):
        with patch.dict(os.environ,{'HOSTNAME':'manager'}):return mirror_jobs.create(self.engine,'a'*32,self.request)
    def test_missing_old_image_uses_only_the_qualified_packaged_helper(self):
        self.assertEqual(self.create(),'new-job')
        body=self.engine.created[0]
        self.assertEqual(body['Image'],'sha256:new')
        self.assertEqual(body['HostConfig']['NetworkMode'],'none')
        self.assertTrue(body['HostConfig']['Mounts'][0]['ReadOnly'])
        self.assertEqual(body['HostConfig']['Mounts'][1]['Source'],'/home/test/backups')
    def test_available_original_image_stays_pinned_and_does_not_follow_a_tag(self):
        self.engine.original={'Id':'sha256:old'}
        self.create()
        self.assertEqual(self.engine.created[0]['Image'],'sha256:old')
        self.assertNotIn('/images/dst-docker-manager%3Alocal/json',self.engine.reads)
    def test_missing_or_unqualified_fallback_never_creates_a_job(self):
        for fallback in (None,{'Id':'untrusted','Config':{'Labels':{}}},
                         {'Id':'wrong-protocol','Config':{'Labels':{'io.dst.backup-mirror-helper':'2'}}}):
            self.engine.fallback=fallback
            with self.assertRaisesRegex(ValueError,'mirror helper image is unavailable'):self.create()
        self.assertEqual(self.engine.created,[])
    def test_arbitrary_image_arguments_cannot_enter_the_fixed_mirror_payload(self):
        self.request['image']='attacker/image'
        self.create()
        self.assertEqual(self.engine.created[0]['Image'],'sha256:new')
        self.assertNotIn('attacker',str(self.engine.created))


if __name__=='__main__':unittest.main()
