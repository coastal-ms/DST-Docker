"""WSL config preservation and the actual piped installer restart boundary."""
import hashlib
import contextlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from build_installer import package
import test_installer as installer

TEMPLATE = installer.TEMPLATE

CODE = TEMPLATE.read_text().split("<<'DST_WSL_PY'\n", 1)[1].split('\nDST_WSL_PY', 1)[0]
module = {'__name__': 'wsl_setup_test'}
exec(compile(CODE, str(TEMPLATE), 'exec'), module)


class WslConfigTests(unittest.TestCase):
    def test_preserves_existing_sections_comments_crlf_bom_mode_and_backup(self):
        original = b'\xef\xbb\xbf# user settings\r\n[automount]\r\nroot=/windows/\r\n[boot]\r\ncommand=echo ready\r\nSystemd = false # user comment\r\n[interop]\r\nenabled=true\r\n'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'wsl.conf';path.write_bytes(original);path.chmod(0o640)
            module['enable_systemd'](path)
            self.assertEqual(path.read_bytes(), original.replace(b'false',b'true'))
            self.assertEqual(path.stat().st_mode & 0o777,0o640)
            backups=list(path.parent.glob('wsl.conf.dst-backup-*'))
            self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),original)
            module['enable_systemd'](path)
            self.assertEqual(len(list(path.parent.glob('wsl.conf.dst-backup-*'))),1)

    def test_missing_boot_and_missing_key_preserve_all_other_content(self):
        samples = {
            b'':b'[boot]\nsystemd=true\n',
            b'[user]\ndefault=test':b'[user]\ndefault=test\n[boot]\nsystemd=true\n',
            b'[boot]\ncommand=hello\n[network]\ngenerateHosts=false\n':b'[boot]\ncommand=hello\nsystemd=true\n[network]\ngenerateHosts=false\n',
            b'[boot]\nsystemd=false\nsystemd = false\n':b'[boot]\nsystemd=true\nsystemd = true\n',
        }
        for old, expected in samples.items():
            with self.subTest(old=old), tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'wsl.conf'
                if old:path.write_bytes(old)
                module['enable_systemd'](path);self.assertEqual(path.read_bytes(),expected)

    def test_refuses_symlinks_and_unreadable_config_without_overwriting(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'user-settings';target.write_text('preserve')
            link=root/'wsl.conf';link.symlink_to(target)
            with self.assertRaises(ValueError):module['enable_systemd'](link)
            self.assertEqual(target.read_text(),'preserve');link.unlink()
            link.write_bytes(b'\xffinvalid')
            with self.assertRaises(UnicodeDecodeError):module['enable_systemd'](link)
            self.assertEqual(link.read_bytes(),b'\xffinvalid')

    def test_failure_to_commit_keeps_original_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'wsl.conf';path.write_text('[boot]\nsystemd=false\n')
            with patch('os.replace',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):module['enable_systemd'](path)
            self.assertIn('false',path.read_text());self.assertFalse(list(path.parent.glob('.dst-wsl-*')))

    def test_restart_script_targets_one_distro_and_treats_names_as_data(self):
        script=module['restart_script']("USER's Test; Write-Host bad",'test user','/tmp/setup path/resume.sh',False)
        self.assertIn("'USER''s Test; Write-Host bad'",script)
        self.assertIn("'--terminate'",script);self.assertNotIn('--shutdown',script)
        self.assertIn("'--user','test user'",script)
        self.assertIn('if($false)',script)
        self.assertIn('WaitForExit(120000)',script)

    def test_missing_interop_gives_exact_saved_resume_command(self):
        with patch('shutil.which',return_value=None):
            with self.assertRaisesRegex(ValueError,'bash /tmp/setup/resume.sh'):
                module['launch']('Fixture','tester','/tmp/setup/resume.sh')

    def test_initializes_only_missing_machine_ids_and_keeps_existing_identity(self):
        for old in (None,b'',b'uninitialized\n',b'0'*32+b'\n',b'a'*32+b'\n'):
            with self.subTest(old=old), tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'machine-id'
                if old is not None:path.write_bytes(old)
                module['initialize_machine_id'](path)
                result=path.read_bytes()
                self.assertRegex(result,rb'^[0-9a-f]{32}\n$')
                if old==b'a'*32+b'\n':self.assertEqual(result,old)
                else:self.assertEqual(path.stat().st_mode & 0o777,0o444)
                module['initialize_machine_id'](path);self.assertEqual(path.read_bytes(),result)

    def test_machine_id_symlink_and_unknown_invalid_value_are_left_intact(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'target';target.write_bytes(b'preserve')
            path=Path(folder)/'machine-id';path.symlink_to(target)
            with self.assertRaises(ValueError):module['initialize_machine_id'](path)
            self.assertEqual(target.read_bytes(),b'preserve');path.unlink()
            path.write_bytes(b'unknown-machine-id')
            with self.assertRaises(ValueError):module['initialize_machine_id'](path)
            self.assertEqual(path.read_bytes(),b'unknown-machine-id')

    def test_stage_uses_private_persistent_user_cache_instead_of_boot_cleaned_tmp(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(Path,'home',return_value=Path(folder)):
            output=io.StringIO()
            with contextlib.redirect_stdout(output):module['main'](['stage'])
            stage=Path(output.getvalue().strip())
            self.assertEqual(stage.parent,Path(folder)/'.cache/dst-docker-setup')
            self.assertEqual(stage.stat().st_mode & 0o777,0o700)
            self.assertEqual(stage.parent.stat().st_mode & 0o777,0o700)

    def test_configure_installs_missing_systemd_sysv_before_changing_boot_settings(self):
        calls=[]
        def run(args,**kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args,0,stdout='install ok installed' if args[-1]=='systemd' else '',stderr='')
        with patch('subprocess.run',side_effect=run), patch.dict(module,initialize_machine_id=lambda:calls.append('identity'),enable_systemd=lambda:calls.append('config')):
            module['main'](['configure'])
        self.assertIn(['apt-get','install','-y','systemd-sysv'],calls)
        self.assertEqual(calls[-2:],['identity','config'])


class WslInstallerFlowTests(unittest.TestCase):
    def setUp(self):
        self.fixture=installer.InstallerTests();self.fixture.setUp()
        self.root=self.fixture.root;self.env=self.fixture.environment
        self.env['WSL_DISTRO_NAME']='Fixture USER Test'
        self.env['DST_WSL_FIXTURE']=str(self.root/'wsl-calls')
        self.env['HOME']=str(self.root/'home')
        self.mode=self.root/'init';self.mode.write_text('init(Fixture)')
        self.env['DST_WSL_INIT']=str(self.mode)
        ps=self.fixture.fake/'ps';ps.write_text('#!/bin/sh\ncat "$DST_WSL_INIT"\n');ps.chmod(0o755)
        sudo=self.fixture.fake/'sudo';sudo.write_text('#!/bin/sh\nexec "$@"\n');sudo.chmod(0o755)
        # Only the external configuration/restart actions are mocked. Snapshot,
        # argument handling, piped input and resumed source preparation are real.
        helper='''dst_wsl_helper() {
  if [[ "$1" == stage ]]; then mkdir -p "$HOME"; mktemp -d "$HOME/dst-wsl-setup.XXXXXXXX"; return; fi
  printf '%s\\n' "$*" >> "$DST_WSL_FIXTURE"
}
'''
        template=TEMPLATE.read_text()
        start=template.index('dst_wsl_helper() {')
        end=template.index('\ndst_prepare_wsl() {',start)
        template=template[:start]+helper+template[end:]
        template=template.replace('/run/systemd/first-boot',str(self.root/'firstboot-marker'))
        self.payload=installer.archive()
        self.fixture.script.write_bytes(package(template,self.payload,'a'*40,'1.0.6'))
        self.prefix=self.root/'destination with spaces'
        self.resume=None

    def tearDown(self):
        if self.resume and self.resume.parent.exists():
            import shutil
            shutil.rmtree(self.resume.parent)
        self.fixture.tearDown()

    def test_unattended_waits_for_restart_and_resumes_exact_source_and_options(self):
        result=self.fixture.run_installer('--prepare-only','--prefix',str(self.prefix),'--port','9191')
        self.assertEqual(result.returncode,75,result.stderr)
        self.assertFalse(self.prefix.exists())
        self.assertIn('wsl --terminate "Fixture USER Test"',result.stdout)
        self.assertNotIn('launch',Path(self.env['DST_WSL_FIXTURE']).read_text())
        self.resume=Path(re.search(r'bash (\S+/dst-wsl-setup\.[^\s]+/resume.sh)',result.stdout)[1])
        self.assertEqual((self.resume.parent/'source.tar').read_bytes(),self.payload)
        self.mode.write_text('systemd')
        result=subprocess.run(['bash',str(self.resume)],env=self.env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        state=json.loads((self.prefix/'installation.json').read_text())
        self.assertEqual(state['preparedSha256'],hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(state['preparedRevision'],'a'*40)
        self.assertEqual(state['pendingConsolePort'],9191)
        self.assertFalse(self.resume.parent.exists())

    def test_explicit_restart_hands_off_and_resumed_failure_does_not_loop(self):
        result=self.fixture.run_installer('--restart-wsl','--prepare-only','--prefix',str(self.prefix))
        self.assertEqual(result.returncode,0,result.stderr)
        calls=Path(self.env['DST_WSL_FIXTURE']).read_text()
        self.assertIn('launch Fixture USER Test',calls)
        self.resume=Path(re.search(r'(\S+/dst-wsl-setup\.[^\s]+/resume.sh)',calls)[1])
        result=subprocess.run(['bash',str(self.resume)],env=self.env,capture_output=True,text=True,timeout=20)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('WSL did not start systemd',result.stderr)
        self.assertEqual(Path(self.env['DST_WSL_FIXTURE']).read_text(),calls)
        self.assertTrue(self.resume.exists())

    def test_check_mode_makes_no_configuration_or_restart_changes(self):
        result=self.fixture.run_installer('--check','--prefix',str(self.prefix))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(Path(self.env['DST_WSL_FIXTURE']).exists())
        self.assertFalse(self.prefix.exists())

    def test_remote_docker_target_is_rejected_before_wsl_configuration_or_restart(self):
        self.env['DOCKER_HOST']='tcp://fixture.invalid:2376'
        result=self.fixture.run_installer('--restart-wsl','--prefix',str(self.prefix))
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Select the local Linux Docker Engine',result.stderr)
        self.assertFalse(Path(self.env['DST_WSL_FIXTURE']).exists())
        self.assertFalse(self.prefix.exists())

    def test_piped_handoff_keeps_source_and_full_install_resumes_with_port(self):
        result=subprocess.run(['bash','-s','--','--non-interactive','--restart-wsl','--prefix',str(self.prefix),'--port','9292'],input=self.fixture.script.read_text(),env=self.env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        calls=Path(self.env['DST_WSL_FIXTURE']).read_text()
        self.resume=Path(re.search(r'(\S+/dst-wsl-setup\.[^\s]+/resume.sh)',calls)[1])
        self.mode.write_text('systemd')
        result=subprocess.run(['bash',str(self.resume)],env=self.env,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('portal fixture started up --port 9292',result.stdout)
        state=json.loads((self.prefix/'installation.json').read_text())
        self.assertEqual(state['activeSha256'],hashlib.sha256(self.payload).hexdigest())
        self.assertFalse(self.resume.parent.exists())

    def test_existing_firstboot_stall_is_cleared_before_dependencies(self):
        self.mode.write_text('systemd');(self.root/'firstboot-marker').touch()
        self.env['DST_WSL_SYSTEMCTL_LOG']=str(self.root/'systemctl-calls')
        systemctl=self.fixture.fake/'systemctl'
        systemctl.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$DST_WSL_SYSTEMCTL_LOG"
if [ "$1" = show ]; then
  if [ -e "$DST_WSL_INIT.stopped" ]; then echo dead; else echo start; fi
fi
if [ "$1" = stop ]; then touch "$DST_WSL_INIT.stopped"; fi
''');systemctl.chmod(0o755)
        result=self.fixture.run_installer('--prepare-only','--prefix',str(self.prefix))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(Path(self.env['DST_WSL_SYSTEMCTL_LOG']).read_text().count('stop systemd-firstboot.service'),1)
        self.assertIn('Completing imported WSL first-boot setup',result.stdout)
        self.assertFalse(Path(self.env['DST_WSL_FIXTURE']).exists())

    def test_interactive_restart_requires_the_terminal_answer(self):
        for answer,expected in [('n\n',75),('\n',0)]:
            with self.subTest(answer=answer):
                master,slave=installer.pty.openpty()
                def terminal():
                    os.setsid();installer.fcntl.ioctl(slave,installer.termios.TIOCSCTTY,0)
                process=subprocess.Popen(['bash','-s','--','--prepare-only','--prefix',str(self.prefix)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=self.env,pass_fds=(slave,),preexec_fn=terminal)
                os.close(slave)
                def send_script():
                    try:process.stdin.write(self.fixture.script.read_text());process.stdin.close()
                    except (BrokenPipeError,ValueError):pass
                writer=installer.threading.Thread(target=send_script,daemon=True);writer.start()
                transcript=''
                try:
                    deadline=installer.time.monotonic()+10
                    while '[Y/n]:' not in transcript and installer.time.monotonic()<deadline:
                        if installer.select.select([master],[],[],.1)[0]:transcript+=os.read(master,4096).decode()
                    self.assertIn('All processes in this distribution will stop',transcript)
                    os.write(master,answer.encode());writer.join(timeout=10);process.stdin=None
                    output,error=process.communicate(timeout=15)
                    self.assertEqual(process.returncode,expected,error)
                    if expected==75:self.resume=Path(re.search(r'bash (\S+/dst-wsl-setup\.[^\s]+/resume.sh)',output)[1])
                    else:self.resume=Path(re.search(r'(\S+/dst-wsl-setup\.[^\s]+/resume.sh)',Path(self.env['DST_WSL_FIXTURE']).read_text())[1])
                    import shutil
                    shutil.rmtree(self.resume.parent);self.resume=None
                finally:
                    if process.poll() is None:process.kill();process.wait()
                    for stream in (process.stdin,process.stdout,process.stderr):
                        if stream:stream.close()
                    os.close(master)


if __name__=='__main__':unittest.main()
