import hashlib,io,json,os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from build_installer import package

TEMPLATE=Path(__file__).parent.parent.parent/'bin/dst-install'
# In the Docker test mount only this directory is provided separately.
if not TEMPLATE.exists():TEMPLATE=Path('/installer-template')

def archive(extra=None):
    output=io.BytesIO()
    files={'bin/dst-docker':b'#!/bin/sh\nprintf "portal fixture started\\n"\n','compose.yaml':b'name: fixture\nservices: {}\n','packaging/docker/Dockerfile':b'FROM scratch\n'}
    with tarfile.open(fileobj=output,mode='w:gz') as target:
        for name,data in files.items():
            entry=tarfile.TarInfo(name);entry.size=len(data);entry.mode=0o755 if name.startswith('bin/') else 0o644;target.addfile(entry,io.BytesIO(data))
        if extra:target.addfile(extra)
    return output.getvalue()

class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name);self.fake=self.root/'commands';self.fake.mkdir()
        self.log=self.root/'docker-calls';self.environment={**os.environ,'PATH':str(self.fake)+':'+os.environ['PATH'],'DST_FIXTURE_DOCKER_LOG':str(self.log)}
        docker=self.fake/'docker';docker.write_text('''#!/bin/sh
printf '%s\n' "$*" >> "$DST_FIXTURE_DOCKER_LOG"
case "$1" in
  info) case "$*" in *OperatingSystem*) printf 'Ubuntu fixture\n';; *) printf 'linux\n';; esac;;
  context) printf 'unix:///var/run/docker.sock\n';;
  version) printf '1.56\n';;
  compose) exit 0;;
  *) exit 99;;
esac
''');docker.chmod(0o755)
        self.script=self.root/'installer.sh';self.script.write_bytes(package(TEMPLATE.read_text(),'placeholder'.encode(),'a'*40))
    def tearDown(self):self.temporary.cleanup()
    def run_installer(self,*args,input=None):
        return subprocess.run(['bash',str(self.script),*args],input=input,text=True,capture_output=True,env=self.environment,timeout=20)
    def bundle(self,data=None):
        payload=data if data is not None else archive();self.script.write_bytes(package(TEMPLATE.read_text(),payload,'a'*40));return payload

    def test_check_mode_changes_no_install_files_and_makes_no_docker_mutations(self):
        prefix=self.root/'installation';result=self.run_installer('--check','--prefix',str(prefix))
        self.assertEqual(result.returncode,0,result.stderr);self.assertFalse(prefix.exists())
        self.assertTrue(all(line.startswith(('compose version','info ')) for line in self.log.read_text().splitlines()))

    def test_standalone_package_can_be_piped_and_prepared_without_a_clone_or_portal_start(self):
        self.bundle();prefix=self.root/'installation'
        result=subprocess.run(['bash','-s','--','--prepare-only','--prefix',str(prefix)],input=self.script.read_text(),text=True,capture_output=True,env=self.environment,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr);state=json.loads((prefix/'installation.json').read_text())
        self.assertTrue((prefix/'releases'/state['preparedSha256']/'bin/dst-docker').is_file());self.assertNotIn('activeSha256',state)
        self.assertFalse(any(' up' in line or 'build' in line or ' run' in line for line in self.log.read_text().splitlines()))

    def test_prepare_is_repeatable_and_preserves_other_install_metadata(self):
        self.bundle();prefix=self.root/'installation'
        first=self.run_installer('--prepare-only','--prefix',str(prefix));self.assertEqual(first.returncode,0,first.stderr)
        state=json.loads((prefix/'installation.json').read_text());state['operatorNote']='preserve me';(prefix/'installation.json').write_text(json.dumps(state))
        second=self.run_installer('--prepare-only','--prefix',str(prefix));self.assertEqual(second.returncode,0,second.stderr)
        self.assertEqual(json.loads((prefix/'installation.json').read_text())['operatorNote'],'preserve me')
        self.assertEqual(len(list((prefix/'releases').iterdir())),1)

    def test_prepared_source_directories_are_readable_by_the_nonroot_container_user(self):
        self.bundle();prefix=self.root/'installation'
        result=self.run_installer('--prepare-only','--prefix',str(prefix));self.assertEqual(result.returncode,0,result.stderr)
        state=json.loads((prefix/'installation.json').read_text());source=prefix/'releases'/state['preparedSha256']
        for relative in ['bin','packaging','packaging/docker']:
            self.assertEqual((source/relative).stat().st_mode&0o777,0o755)
        self.assertEqual((source/'packaging/docker/Dockerfile').stat().st_mode&0o777,0o644)
        self.assertEqual((prefix/'installation.json').stat().st_mode&0o777,0o600)

    def test_refuses_unmarked_nonempty_destination(self):
        self.bundle();prefix=self.root/'not-dst';prefix.mkdir();(prefix/'important.txt').write_text('keep')
        result=self.run_installer('--prepare-only','--prefix',str(prefix));self.assertNotEqual(result.returncode,0)
        self.assertEqual((prefix/'important.txt').read_text(),'keep');self.assertFalse((prefix/'releases').exists())

    def test_rejects_symlink_parent_and_parent_traversal_without_writing_target(self):
        self.bundle();outside=self.root/'outside';outside.mkdir();link=self.root/'alias';link.symlink_to(outside,target_is_directory=True)
        for prefix in [link/'install',self.root/'missing'/'..'/'traversal']:
            with self.subTest(prefix=str(prefix)):
                result=self.run_installer('--prepare-only','--prefix',str(prefix));self.assertNotEqual(result.returncode,0)
                self.assertFalse((outside/'install').exists());self.assertFalse((self.root/'traversal').exists())

    def test_failed_portal_start_keeps_previous_active_release_and_data(self):
        self.bundle();prefix=self.root/'installation'
        result=self.run_installer('--prefix',str(prefix));self.assertEqual(result.returncode,0,result.stderr)
        state=json.loads((prefix/'installation.json').read_text());active=state['activeSha256'];target=(prefix/'current').resolve()
        original=archive();incoming=io.BytesIO()
        with tarfile.open(fileobj=io.BytesIO(original)) as old,tarfile.open(fileobj=incoming,mode='w:gz') as new:
            for entry in old:
                data=old.extractfile(entry).read()
                if entry.name=='bin/dst-docker':data=b'#!/bin/sh\nexit 23\n'
                entry.size=len(data);new.addfile(entry,io.BytesIO(data))
        self.bundle(incoming.getvalue());result=self.run_installer('--prefix',str(prefix));self.assertNotEqual(result.returncode,0)
        final=json.loads((prefix/'installation.json').read_text());self.assertEqual(final['activeSha256'],active)
        self.assertEqual((prefix/'current').resolve(),target);self.assertNotEqual(final['preparedSha256'],active)

    def test_archive_traversal_and_symlinks_are_rejected_before_destination_creation(self):
        for name,kind in [('../outside',tarfile.REGTYPE),('link',tarfile.SYMTYPE)]:
            with self.subTest(name=name):
                entry=tarfile.TarInfo(name);entry.type=kind;entry.linkname='/outside';self.bundle(archive(entry));prefix=self.root/('rejected-'+kind.decode())
                result=self.run_installer('--prepare-only','--prefix',str(prefix));self.assertNotEqual(result.returncode,0);self.assertFalse(prefix.exists())

    def test_rejects_tampered_payload_without_unpacking(self):
        self.bundle();self.script.write_text(self.script.read_text().replace("task_package_sha='", "task_package_sha='0",1));prefix=self.root/'tampered'
        result=self.run_installer('--prepare-only','--prefix',str(prefix));self.assertNotEqual(result.returncode,0);self.assertIn('checksum',result.stderr);self.assertFalse(prefix.exists())

    def test_successful_launch_activates_only_the_qualified_source_release(self):
        payload=self.bundle();prefix=self.root/'installation';result=self.run_installer('--prefix',str(prefix))
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('portal fixture started',result.stdout)
        state=json.loads((prefix/'installation.json').read_text());self.assertEqual(state['activeSha256'],hashlib.sha256(payload).hexdigest())
        self.assertEqual((prefix/'current').resolve(),(prefix/'releases'/state['activeSha256']).resolve())

    def test_rejects_old_engine_api_before_extracting_source(self):
        self.bundle();path=self.fake/'docker';path.write_text(path.read_text().replace("printf '1.56", "printf '1.44"));prefix=self.root/'old-engine'
        result=self.run_installer('--prepare-only','--prefix',str(prefix));self.assertNotEqual(result.returncode,0);self.assertIn('Engine 26',result.stderr);self.assertFalse(prefix.exists())

if __name__=='__main__':unittest.main()
