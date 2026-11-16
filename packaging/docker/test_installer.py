import hashlib,io,json,os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
import pty,fcntl,termios,select,time,threading
from build_installer import package

TEMPLATE=Path(__file__).parent.parent.parent/'bin/dst-install'
# In the Docker test mount only this directory is provided separately.
if not TEMPLATE.exists():TEMPLATE=Path('/installer-template')

def archive(extra=None,launcher=None,updater=None):
    output=io.BytesIO()
    files={'bin/dst-docker':b'#!/bin/sh\nprintf "portal fixture started %s\\n" "$*"\n','compose.yaml':b'name: fixture\nservices: {}\n','packaging/docker/host_session.py':b'import sys;print("shortcut fixture prepared "+" ".join(sys.argv[1:]))\n','packaging/docker/Dockerfile':b'FROM scratch\n'}
    if launcher is not None:files['bin/dst-docker']=launcher
    if updater is not None:files['packaging/docker/portal_update.py']=updater
    with tarfile.open(fileobj=output,mode='w:gz') as target:
        for name,data in files.items():
            entry=tarfile.TarInfo(name);entry.size=len(data);entry.mode=0o755 if name.startswith('bin/') else 0o644;target.addfile(entry,io.BytesIO(data))
        if extra:target.addfile(extra)
    return output.getvalue()

class InstallerTests(unittest.TestCase):
    def test_update_service_prepared_before_portal_and_registered_after_activation(self):
        sudo=self.fake/'sudo';sudo.write_text('#!/bin/sh\nexec "$@"\n');sudo.chmod(0o755)
        helper=b'import sys;from pathlib import Path;root=Path(sys.argv[-1]);print("updater "+sys.argv[1]);assert (root/"current").is_symlink() if sys.argv[1]=="register" else not (root/"current").exists()\n'
        self.bundle(archive(updater=helper))
        ps=self.fake/'ps';ps.write_text('#!/bin/sh\necho systemd\n');ps.chmod(0o755)
        prefix=self.root/'installed'
        result=self.run_installer('--prefix',str(prefix))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertLess(result.stdout.index('updater prepare'),result.stdout.index('portal fixture started'))
        self.assertGreater(result.stdout.index('updater register'),result.stdout.index('portal fixture started'))
        self.environment['DST_SELF_UPDATE']='1'
        result=self.run_installer('--prefix',str(self.root/'self-update'))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('updater prepare',result.stdout)
        self.assertNotIn('updater register',result.stdout)

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name);self.fake=self.root/'commands';self.fake.mkdir()
        self.log=self.root/'docker-calls';self.environment={**os.environ,'PATH':str(self.fake)+':'+os.environ['PATH'],'DST_FIXTURE_DOCKER_LOG':str(self.log)}
        self.environment.pop('WSL_DISTRO_NAME',None)
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
        systemctl=self.fake/'systemctl';systemctl.write_text('#!/bin/sh\nexit 0\n');systemctl.chmod(0o755)
    def tearDown(self):self.temporary.cleanup()
    def run_installer(self,*args,input=None):
        return subprocess.run(['bash',str(self.script),'--non-interactive',*args],input=input,text=True,capture_output=True,env=self.environment,timeout=20)
    def bundle(self,data=None):
        payload=data if data is not None else archive();self.script.write_bytes(package(TEMPLATE.read_text(),payload,'a'*40));return payload

    def interactive_install(self,*args,answers=None):
        master,slave=pty.openpty()
        def terminal():
            os.setsid();fcntl.ioctl(slave,termios.TIOCSCTTY,0)
        process=subprocess.Popen(['bash','-s','--',*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,env=self.environment,pass_fds=(slave,),preexec_fn=terminal)
        os.close(slave);transcript=''
        def send_script():
            try:process.stdin.write(self.script.read_text());process.stdin.close()
            except (BrokenPipeError,ValueError):pass
        writer=threading.Thread(target=send_script,daemon=True);writer.start()
        try:
            if answers is not None:
                deadline=time.monotonic()+10
                while 'press Enter to use 8088' not in transcript and time.monotonic()<deadline:
                    if select.select([master],[],[],.1)[0]:transcript+=os.read(master,4096).decode()
                self.assertIn('press Enter to use 8088',transcript)
                os.write(master,answers.encode())
            writer.join(timeout=10)
            if writer.is_alive():raise TimeoutError('Piped installer did not consume its source')
            process.stdin=None
            output,error=process.communicate(timeout=15)
            return process.returncode,output,error,transcript
        finally:
            if process.poll() is None:process.kill();process.wait()
            os.close(master)

    def test_wsl_install_prepares_desktop_shortcut_after_activating_source(self):
        self.bundle();self.environment['WSL_DISTRO_NAME']='Ubuntu'
        ps=self.fake/'ps';ps.write_text('#!/bin/sh\nprintf "systemd\\n"\n');ps.chmod(0o755)
        docker=self.fake/'docker';docker.write_text(docker.read_text().replace('compose) exit 0;;','compose) echo \'{"name":"fixture"}\'; exit 0;;'))
        result=self.run_installer('--prefix',str(self.root/'installed'))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('shortcut fixture prepared prepare',result.stdout)
        self.assertIn('--project fixture',result.stdout)
        self.assertIn('desktop icon',result.stdout)
        self.assertNotIn('You can close this terminal',result.stdout)
        self.assertTrue((self.root/'installed/current').is_symlink())

    def test_piped_installer_activates_source_even_when_launcher_reads_stdin(self):
        self.bundle(archive(launcher=b'#!/bin/sh\ncat >/dev/null\nprintf "portal fixture started\\n"\n'))
        prefix=self.root/'piped-active'
        code,output,error,_=self.interactive_install('--prefix',str(prefix),'--non-interactive')
        self.assertEqual(code,0,error)
        self.assertIn('[5/5] DST setup is ready',output)
        state=json.loads((prefix/'installation.json').read_text())
        self.assertEqual(state['activeSha256'],state['preparedSha256'])
        self.assertEqual((prefix/'current').resolve().name,state['activeSha256'])

    def test_piped_interactive_install_reads_port_from_terminal_and_reprompts_invalid_answer(self):
        self.bundle();prefix=self.root/'interactive'
        code,output,error,_=self.interactive_install('--prefix',str(prefix),answers='80\n9191\n')
        self.assertEqual(code,0,error);self.assertIn('portal fixture started up --port 9191',output)

    def test_interactive_enter_selects_default_and_scripted_mode_does_not_prompt(self):
        self.bundle()
        code,output,error,_=self.interactive_install('--prefix',str(self.root/'default'),answers='\n')
        self.assertEqual(code,0,error);self.assertIn('portal fixture started up --port 8088',output)
        code,output,error,_=self.interactive_install('--prefix',str(self.root/'scripted'),'--non-interactive')
        self.assertEqual(code,0,error);self.assertNotIn('Enter the Web UI port',output)

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

    def test_selected_console_port_survives_prepare_and_is_consumed_by_start(self):
        self.bundle();prefix=self.root/'installation'
        result=self.run_installer('--prepare-only','--prefix',str(prefix),'--port','9090')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads((prefix/'installation.json').read_text())['pendingConsolePort'],9090)
        result=self.run_installer('--prefix',str(prefix))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('portal fixture started up --port 9090',result.stdout)
        self.assertNotIn('pendingConsolePort',json.loads((prefix/'installation.json').read_text()))
        result=self.run_installer('--prefix',str(prefix))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('--port',result.stdout)

    def test_invalid_console_ports_fail_before_install_or_docker_changes(self):
        for port in ['0','80','65536','8088;bad','not-a-port','08088']:
            result=self.run_installer('--port',port,'--prefix',str(self.root/'installation'))
            self.assertNotEqual(result.returncode,0)
            self.assertIn('console port',result.stderr)
        self.assertFalse((self.root/'installation').exists());self.assertFalse(self.log.exists())

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
