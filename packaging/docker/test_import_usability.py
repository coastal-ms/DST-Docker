import os
import unittest
from unittest.mock import Mock, patch
import engine
import manager
import backup_schedule


class AppDiscovery(engine.Engine):
    def __init__(self, running=1): self.running=running; self.calls=[]
    def ensure_owned_volume(self,*args): pass
    def upload_component_files(self,*args): pass
    def inspect(self, identifier):
        if identifier=='manager': return {'Config':{'Labels':{'com.docker.compose.project':'fixture'}}}
        return {'Mounts':[{'Type':'volume','Destination':'/data/cache','Name':'fixture-cache'}]}
    def request(self,method,path,body=None,expected=None,timeout=30):
        self.calls.append((method,path,body))
        if path.startswith('/containers/json?'):
            # A real Docker API returns stopped apps only with all=true.
            return [{'Id':'active'}]*self.running+([{'Id':'stopped'}] if 'all=true' in path else [])
        if path.startswith('/volumes/'): return {'Labels':{'com.docker.compose.project':'fixture','com.docker.compose.volume':'dst-cache'}}
        if path.startswith('/containers/create?'): return {'Id':'job'}
        if path.startswith('/containers/'): return None
        raise AssertionError(path)


class ImportUsabilityTests(unittest.TestCase):
    def test_stopped_app_does_not_block_import_but_two_running_apps_still_do(self):
        request={'uploadId':'b'*32,'name':'backup-123-abcdef12.dump','sha256':'c'*64,'bytes':512}
        image='registry.funcom.com/funcom/self-hosting/seabass-server-db-utils:fixture'
        with patch.dict(os.environ,{'HOSTNAME':'manager'}):
            client=AppDiscovery()
            self.assertEqual(client.create_backup_import_job('a'*32,image,request,'script'),'job')
            spec=next(body for method,path,body in client.calls if method=='POST')
            self.assertEqual(spec['HostConfig']['Mounts'][0]['Source'],'fixture-cache')
            for count in [0,2]:
                client=AppDiscovery(count)
                with self.assertRaisesRegex(ValueError,'Exactly one'):client.create_backup_import_job('a'*32,image,request,'script')
                self.assertFalse(any(method=='POST' for method,_,_ in client.calls))

    def test_import_filename_survives_resume_and_history_without_becoming_a_storage_path(self):
        state={'id':'a'*32,'backups':{}}
        request={'uploadId':'b'*32,'sha256':'c'*64,'bytes':512,'trustedSource':True,'originalFilename':'My world 100% – 漢字.backup'}
        worker=Mock(spec=manager.Engine);worker.create_backup_import_job.return_value='job';worker.assert_owned.return_value={'State':{'Status':'running'}}
        assets={'images':[{'archive':'battlegroup/server-db-utils.tar','tags':['registry.funcom.com/funcom/self-hosting/seabass-server-db-utils:fixture']}]}
        with patch.object(manager,'save'),patch.object(manager,'assets_state',return_value=assets),patch.object(manager.Path,'read_text',return_value='script'):
            manager.start_backup_import(state,worker,request)
            manager.start_backup_import(state,worker,request)
            with self.assertRaisesRegex(ValueError,'does not match'):manager.start_backup_import(state,worker,{**request,'originalFilename':'other.backup'})
        entry=state['backups'][request['uploadId']];self.assertEqual(entry['originalFilename'],request['originalFilename'])
        self.assertRegex(entry['name'],r'^backup-[0-9]+-[a-f0-9]{8}\.dump$')
        entry['phase']='completed';row=backup_schedule.history(state)['recent'][0]
        self.assertEqual(row['originalFilename'],request['originalFilename']);self.assertEqual(row['path'],'/backups/'+entry['name'])
        entry.pop('originalFilename');self.assertEqual(backup_schedule.history(state)['recent'][0]['originalFilename'],'')

    def test_filename_paths_controls_and_oversized_metadata_are_rejected_before_any_job(self):
        for name in ['../world.backup',r'C:\world.backup','bad\nname','.', '..','x'*256,None]:
            state={'id':'a'*32,'backups':{}};worker=Mock(spec=manager.Engine)
            with self.assertRaises(ValueError):manager.start_backup_import(state,worker,{'uploadId':'b'*32,'sha256':'c'*64,'bytes':512,'trustedSource':True,'originalFilename':name})
            worker.create_backup_import_job.assert_not_called();self.assertEqual(state['backups'],{})


if __name__=='__main__': unittest.main()
