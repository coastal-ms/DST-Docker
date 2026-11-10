import fcntl,hashlib,json,os,tempfile,unittest
from pathlib import Path
import backup_mirror,mirror_config

class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.source=self.root/'source';self.source.mkdir()
        self.dest=self.root/'mirror';mirror_config.prepare('fixture',self.dest,self.root/'mirror.json')
        self.name='backup-12345678-abcdef12.dump';self.data=b'PGDMP-fixture-data';(self.source/self.name).write_bytes(self.data)
        self.request={'id':'a'*32,'project':'b'*32,'composeProject':'fixture','files':[{'name':self.name,'bytes':len(self.data),'sha256':hashlib.sha256(self.data).hexdigest()}]}
        self.world=self.dest/('world-'+'b'*32)
    def tearDown(self):self.temp.cleanup()
    def copy(self):return backup_mirror.copy_backups(self.source,self.dest,self.request)
    def test_repeat_copy_preserves_original_files_and_uses_exact_bytes(self):
        (self.dest/'keep.txt').write_text('keep')
        self.assertTrue(self.copy()['files'][0]['copied']);target=self.world/self.name;inode=target.stat().st_ino
        self.assertFalse(self.copy()['files'][0]['copied'])
        self.assertEqual(target.stat().st_ino,inode);self.assertEqual(target.read_bytes(),self.data)
        self.assertEqual(target.stat().st_mode&0o777,0o600);self.assertEqual(target.stat().st_uid,self.dest.stat().st_uid)
        self.assertEqual((self.dest/'keep.txt').read_text(),'keep');self.assertEqual((self.source/self.name).read_bytes(),self.data)
    def test_existing_different_copy_is_never_overwritten(self):
        self.world.mkdir();(self.world/self.name).write_bytes(b'important preexisting copy')
        with self.assertRaises(ValueError):self.copy()
        self.assertEqual((self.world/self.name).read_bytes(),b'important preexisting copy')
    def test_bad_source_hash_leaves_no_published_copy_or_partial(self):
        self.request['files'][0]['sha256']='c'*64
        with self.assertRaises(ValueError):self.copy()
        self.assertFalse((self.world/self.name).exists());self.assertFalse(list(self.world.glob('*.partial')))
    def test_source_links_and_foreign_destination_are_rejected(self):
        other=self.root/'outside';other.write_bytes(self.data);(self.source/self.name).unlink();(self.source/self.name).symlink_to(other)
        with self.assertRaises(OSError):self.copy()
        (self.source/self.name).unlink();os.link(other,self.source/self.name)
        with self.assertRaises(ValueError):self.copy()
        self.assertEqual(other.read_bytes(),self.data)
        self.request['composeProject']='other'
        with self.assertRaises(ValueError):self.copy()
    def test_interrupted_partial_can_resume_but_an_active_copy_lock_is_preserved(self):
        self.world.mkdir();temporary=self.world/('.dst-mirror-'+self.request['id']+'-'+self.name+'.partial');temporary.write_bytes(b'partial')
        unrelated=self.world/'unrelated.partial';unrelated.write_text('keep')
        self.copy();self.assertFalse(temporary.exists());self.assertEqual(unrelated.read_text(),'keep')
        lock=os.open(self.world/'.dst-mirror.lock',os.O_WRONLY)
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):self.copy()
        finally:os.close(lock)
    def test_destination_symlink_cannot_escape_the_configured_folder(self):
        outside=self.root/'outside-dir';outside.mkdir();self.world.symlink_to(outside,target_is_directory=True)
        with self.assertRaises(OSError):self.copy()
        self.assertEqual(list(outside.iterdir()),[])

class MirrorConfigTests(unittest.TestCase):
    def test_sudo_launch_keeps_new_storage_owned_and_accessible_by_original_user(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);account=SimpleNamespace(pw_uid=65534,pw_gid=65534,pw_dir=str(base/'user-home'))
            with patch.dict(os.environ,{'SUDO_USER':'fixture','SUDO_UID':'65534','SUDO_GID':'65534'},clear=True),patch.object(mirror_config.pwd,'getpwnam',return_value=account):
                folder=mirror_config.default_directory('fixture')
                self.assertEqual(folder,base/'user-home/.local/state/dst-docker/backups/fixture')
                output=base/'mirror.json';mirror_config.prepare('fixture',folder,output)
                self.assertEqual(folder.stat().st_uid,65534);self.assertEqual((folder/mirror_config.MARKER).stat().st_uid,65534)
                self.assertEqual(output.stat().st_uid,65534);self.assertEqual(output.stat().st_mode&0o777,0o600)
                self.assertEqual((base/'user-home/.local/state').stat().st_uid,65534)
            with patch.dict(os.environ,{'SUDO_USER':'fixture','SUDO_UID':'999','SUDO_GID':'65534'},clear=True),patch.object(mirror_config.pwd,'getpwnam',return_value=account):
                with self.assertRaises(ValueError):mirror_config.launch_owner()
    def test_repeated_configuration_keeps_folder_and_marker_and_rejects_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);folder=base/'copies';output=base/'mirror.json'
            first=mirror_config.prepare('fixture',folder,output,'Ubuntu')
            before=output.read_bytes();self.assertEqual(mirror_config.prepare('fixture',folder,output),first);self.assertEqual(output.read_bytes(),before)
            with self.assertRaises(ValueError):mirror_config.prepare('fixture',base/'other',output)
            self.assertEqual(json.loads((folder/mirror_config.MARKER).read_text())['wslDistro'],'Ubuntu')
    def test_system_roots_and_another_installation_marker_are_not_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            for folder in ('/','/etc/private','/root','/var/lib/docker/private'):
                with self.assertRaises(ValueError):mirror_config.prepare('fixture',folder,base/'bad.json')
            folder=base/'copies';folder.mkdir();marker=folder/mirror_config.MARKER;marker.write_text('{"format":1,"composeProject":"other"}')
            with self.assertRaises(ValueError):mirror_config.prepare('fixture',folder,base/'other.json')
            self.assertEqual(json.loads(marker.read_text())['composeProject'],'other')

class MirrorControlTests(unittest.TestCase):
    def test_copy_job_is_durable_and_pending_mirror_sources_are_protected(self):
        import backup_mirror_control as control
        import backup_schedule
        from unittest.mock import Mock
        from engine import Engine
        row={'phase':'completed','name':'backup-1-abcdef12.dump','sha256':'c'*64,'bytes':5,'createdAt':1}
        state={'id':'a'*32,'backups':{'one':dict(row),'two':{**row,'name':'backup-2-abcdef12.dump','createdAt':2}}}
        engine=Mock(spec=Engine);engine.mirror_destination.return_value={'available':True,'folder':'/private/copies'}
        engine.create_backup_mirror_job.return_value='f'*64;engine.assert_owned.return_value={'State':{'Status':'created'}}
        saved=[];save=lambda value:saved.append(value['backupMirror'].get('run',{}).get('phase'))
        control.configure(state,engine,save,True);control.start(state,engine,save)
        run=state['backupMirror']['run'];identifier=run['id']
        self.assertEqual(saved[-2:],['preparing','running']);self.assertEqual(control.protected_ids(state),{'one','two'})
        self.assertEqual(backup_schedule.retained_ids(state,1),[])
        engine.assert_owned.return_value={'State':{'Status':'running'}};control.start(state,engine,save)
        self.assertEqual(run['id'],identifier);engine.lifecycle.assert_called_once_with('f'*64,'a'*32,'start')
        engine.assert_owned.return_value={'State':{'Status':'exited','ExitCode':0}}
        engine.backup_report.return_value={'ok':True,'mode':'mirror','id':identifier,'attempt':0,'project':'a'*32,'files':[{**item,'copied':True} for item in run['files']]}
        control.observe(state,engine,save)
        self.assertEqual(run['phase'],'completed');self.assertEqual(control.protected_ids(state),set())
        self.assertEqual(backup_schedule.retained_ids(state,1),['one']);engine.exec_internal.assert_not_called()

    def test_bad_report_keeps_recovery_sources_and_retry_advances_only_the_attempt(self):
        import backup_mirror_control as control
        from unittest.mock import Mock
        from engine import Engine
        state={'id':'a'*32,'backupMirror':{'enabled':True,'mirrored':{}},'backups':{'one':{'phase':'completed','name':'backup-1-abcdef12.dump','sha256':'c'*64,'bytes':5,'createdAt':1}}}
        engine=Mock(spec=Engine);engine.create_backup_mirror_job.return_value='f'*64
        engine.assert_owned.return_value={'State':{'Status':'created'}}
        control.start(state,engine,lambda _:None);run=state['backupMirror']['run'];identity=run['id']
        engine.assert_owned.return_value={'State':{'Status':'exited','ExitCode':1}};engine.backup_report.return_value={'ok':False}
        control.observe(state,engine,lambda _:None)
        self.assertEqual(run['phase'],'failed');self.assertEqual(control.protected_ids(state),{'one'})
        control.start(state,engine,lambda _:None,retry=True)
        self.assertEqual(run['id'],identity);self.assertEqual(run['attempt'],1)
        control.observe(state,engine,lambda _:None);control.cancel_failed(state,engine,lambda _:None)
        self.assertFalse(state['backupMirror']['enabled']);self.assertEqual(control.protected_ids(state),set())
