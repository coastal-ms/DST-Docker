import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class HttpsLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.prefix=self.root/'installation';self.prefix.mkdir()
        (self.prefix/'installation.json').write_text('{"format":1}')
        self.log=self.root/'calls'
        commands=self.root/'commands';commands.mkdir()
        docker=commands/'docker'
        docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$DST_FIXTURE_DOCKER_LOG"\ncase "$*" in *"config --format json"*) echo \'{"name":"fixture"}\';; *"Get-DuneDockerConsolePort"*) echo 8088;; *"last-url.txt"*) echo \'http://127.0.0.1:18088/?t=synthetic-only\';; esac\nexit 0\n');docker.chmod(0o755)
        self.env={**os.environ,'PATH':str(commands)+':'+os.environ['PATH'],'DST_FIXTURE_DOCKER_LOG':str(self.log)}
        self.env.pop('DST_HTTPS_OVERRIDE',None)
        self.env.pop('DST_MIRROR_OVERRIDE',None)
        self.env.pop('DST_BACKUP_MIRROR_DIR',None)
        self.releases=[]
        for name in ('a'*64,'b'*64):
            release=self.prefix/'releases'/name;(release/'bin').mkdir(parents=True)
            shutil.copy(Path(__file__).parents[2]/'bin/dst-docker',release/'bin/dst-docker')
            (release/'compose.yaml').write_text('name: fixture\nservices: {}\n')
            tools=release/'packaging/docker';tools.mkdir(parents=True)
            shutil.copy(Path(__file__).with_name('portal_urls.py'),tools/'portal_urls.py')
            shutil.copy(Path(__file__).with_name('mirror_config.py'),tools/'mirror_config.py')
            (tools/'https.py').write_text("import json,sys\na=sys.argv; value=lambda flag:a[a.index(flag)+1]\np=value('--output'); old=json.load(open(p))\nif a[1]=='restart-policy':\n old.setdefault('services',{}).setdefault('https',{})['restart']='unless-stopped'; json.dump(old,open(p,'w')); sys.exit()\nold['x-dst-https-origin']='https://'+value('--address')+':'+value('--port'); old['x-dst-http-internal-port']=int(value('--upstream-port')); old['x-dst-https-format']=2; json.dump(old,open(p,'w'))\n")
            self.releases.append(release)
        self.override=self.prefix/'https.compose.json'
        self.override.write_text(json.dumps({'x-dst-https-origin':'https://192.0.2.1:8443','services':{}}))
        (self.prefix/'current').symlink_to('releases/'+self.releases[0].name,target_is_directory=True)

    def tearDown(self):self.temp.cleanup()

    def run_launcher(self,*args,release=0):
        return subprocess.run(['sh',str(self.releases[release]/'bin/dst-docker'),*args],env=self.env,capture_output=True,text=True)

    def test_image_build_failure_does_not_stop_or_replace_running_services(self):
        docker=Path(self.env['PATH'].split(':')[0])/'docker'
        docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$DST_FIXTURE_DOCKER_LOG"\ncase "$*" in *"config --format json"*) echo \'{"name":"fixture"}\';; *" build"*) exit 37;; esac\nexit 0\n')
        docker.chmod(0o755)
        result=self.run_launcher('up')
        self.assertEqual(result.returncode,37,result.stderr)
        calls=self.log.read_text()
        self.assertIn(' build',calls)
        self.assertNotIn(' up ',calls)
        self.assertNotIn(' stop ',calls)
        self.assertNotIn(' down',calls)

    def test_redeploy_forces_recreation_of_only_the_portal(self):
        self.override.unlink()
        self.env['DST_PORTAL_REDEPLOY']='1'
        result=self.run_launcher('up')
        self.assertEqual(result.returncode,0,result.stderr)
        forced=[line for line in self.log.read_text().splitlines() if '--force-recreate' in line]
        self.assertEqual(len(forced),1)
        self.assertTrue(forced[0].endswith('up --no-build -d --no-deps --force-recreate dst'))

    def test_owner_reset_requires_confirmation_and_preserves_the_exact_username_argument(self):
        docker=Path(self.env['PATH'].split(':')[0])/'docker'
        docker.write_text('#!/usr/bin/env python3\nimport json,os,sys\nwith open(os.environ["DST_FIXTURE_DOCKER_LOG"],"a") as stream:stream.write(json.dumps(sys.argv[1:])+"\\n")\n');docker.chmod(0o755)
        command=['sh',str(self.releases[0]/'bin/dst-docker'),'reset-owner','Second Owner']
        cancelled=subprocess.run(command,env=self.env,input='no\n',capture_output=True,text=True)
        self.assertNotEqual(cancelled.returncode,0)
        self.assertFalse(any('exec' in json.loads(line) for line in self.log.read_text().splitlines()))
        confirmed=subprocess.run(command,env=self.env,input='RESET OWNER\n',capture_output=True,text=True)
        self.assertEqual(confirmed.returncode,0,confirmed.stderr)
        calls=[json.loads(line) for line in self.log.read_text().splitlines()]
        invocation=next(args for args in calls if 'exec' in args)
        self.assertEqual(invocation[invocation.index('-Username')+1],'Second Owner')
        self.assertEqual(invocation[invocation.index('-Confirmation')+1],'RESET OWNER')
        self.assertFalse(any(value in {'up','start','build','down'} for args in calls for value in args))

    def test_http_disables_proxy_preserves_configuration_and_recreates_only_console(self):
        original=self.override.read_bytes()
        result=self.run_launcher('http','9090')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(self.override.exists())
        saved=list(self.prefix.glob('https.compose.json.disabled.*'))
        self.assertEqual(len(saved),1)
        self.assertEqual(saved[0].read_bytes(),original)
        calls=self.log.read_text().splitlines()
        stop=next(i for i,line in enumerate(calls) if 'stop https' in line)
        self.assertIn('-f '+str(self.override),calls[stop])
        self.assertTrue(all('-f '+str(self.override) not in line for line in calls[stop+1:]))
        self.assertIn('-Port 9090','\n'.join(calls))
        self.assertIn('up --no-build -d --no-deps dst','\n'.join(calls))
        self.assertFalse(any('volume rm' in line or ' down' in line or 'manager' in line for line in calls))
        self.assertNotIn('https://',result.stdout)

    def test_http_without_tls_preserves_saved_port_and_does_not_touch_proxy(self):
        self.override.unlink()
        result=self.run_launcher('http')
        self.assertEqual(result.returncode,0,result.stderr)
        calls=self.log.read_text()
        self.assertIn('-Port 8088',calls)
        self.assertNotIn('stop https',calls)
        self.assertNotIn('https://',result.stdout)

    def test_invalid_http_port_leaves_https_configuration_untouched(self):
        original=self.override.read_bytes()
        result=self.run_launcher('http','80')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.override.read_bytes(),original)
        self.assertFalse(self.log.exists())

    def test_installer_upgrade_reuses_same_tls_override_outside_both_releases(self):
        for index in (0,1):
            result=self.run_launcher('status',release=index);self.assertEqual(result.returncode,0,result.stderr)
        lines=self.log.read_text().splitlines()
        self.assertEqual(sum('-f '+str(self.override)+' ps' in line for line in lines),2)
        self.assertEqual(json.loads(self.override.read_text())['x-dst-https-origin'],'https://192.0.2.1:8443')

    def test_https_uses_selected_public_port_and_sequences_only_management_services(self):
        result=self.run_launcher('https','192.0.2.1');self.assertEqual(result.returncode,0,result.stderr)
        calls=self.log.read_text()
        self.assertLess(calls.index('stop https'), calls.index('up --no-build -d --no-deps dst'))
        self.assertLess(calls.index('up --no-build -d --no-deps dst'), calls.index('up --no-build -d --no-deps --force-recreate https'))
        self.assertEqual(json.loads(self.override.read_text())['x-dst-https-origin'],'https://192.0.2.1:8088')
        self.assertIn('https://192.0.2.1:8088/?t=synthetic-only', result.stdout)
        self.assertNotIn('http://127.0.0.1:', result.stdout)
        self.assertNotIn('volume create',calls)

    def test_current_symlink_resolves_tls_state_outside_release_and_keeps_it_after_upgrade(self):
        for release in self.releases:
            (self.prefix/'current').unlink()
            (self.prefix/'current').symlink_to('releases/'+release.name,target_is_directory=True)
            result=subprocess.run(['sh',str(self.prefix/'current/bin/dst-docker'),'https','192.0.2.1'],env=self.env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
        calls=self.log.read_text().splitlines()
        self.assertEqual(sum('-f '+str(self.override)+' up --no-build -d --no-deps dst' in line for line in calls),2)
        self.assertFalse(any((release/'https.compose.json').exists() for release in self.releases))

    def test_changed_address_and_port_preserve_external_override_and_reconfigure_management_only(self):
        result=self.run_launcher('https','192.0.2.2','9090');self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(self.override.read_text())['x-dst-https-origin'],'https://192.0.2.2:9090')
        result=self.run_launcher('port','9191');self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(self.override.read_text())['x-dst-https-origin'],'https://192.0.2.2:9191')
        self.assertNotIn('down',self.log.read_text())

    def test_upgrade_preserves_mirror_folder_and_copies_outside_releases(self):
        folder=self.root/'host-backups'
        first=self.run_launcher('mirror-folder',str(folder))
        self.assertEqual(first.returncode,0,first.stderr)
        override=self.prefix/'mirror.compose.json'
        original=override.read_bytes()
        canary=folder/'existing-backup.dump';canary.write_bytes(b'existing backup copy')
        for index in (0,1):
            result=self.run_launcher('mirror-folder',release=index)
            self.assertEqual(result.returncode,0,result.stderr)
            result=self.run_launcher('status',release=index)
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(override.read_bytes(),original)
        self.assertEqual(canary.read_bytes(),b'existing backup copy')
        calls=self.log.read_text().splitlines()
        expected='-f '+str(self.override)+' -f '+str(override)+' ps'
        self.assertEqual(sum(expected in line for line in calls),2)
        self.assertFalse(any((release/'mirror.compose.json').exists() for release in self.releases))
        changed=self.run_launcher('mirror-folder',str(self.root/'different-folder'),release=1)
        self.assertNotEqual(changed.returncode,0)
        self.assertEqual(override.read_bytes(),original)

    def test_up_upgrades_legacy_https_without_changing_selected_secure_address(self):
        prepared=self.run_launcher('mirror-folder',str(self.root/'copies'))
        self.assertEqual(prepared.returncode,0,prepared.stderr)
        result=self.run_launcher('up');self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads(self.override.read_text())
        self.assertEqual(value['x-dst-https-format'],2)
        self.assertEqual(value['x-dst-https-origin'],'https://192.0.2.1:8443')
        self.assertNotEqual(value['x-dst-http-internal-port'],8443)
        calls=self.log.read_text();self.assertLess(calls.index('stop https'),calls.index('up --no-build -d'))
        previous=self.log.read_text().count('stop https')
        result=self.run_launcher('up',release=1);self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.log.read_text().count('stop https'),previous)

    def test_fresh_game_download_starts_after_the_web_ui_link_is_available(self):
        docker=Path(self.env['PATH'].split(':')[0])/'docker'
        docker.write_text(docker.read_text().replace('exit 0\n','case "$*" in *"--entrypoint python3 assets"*) exit 1;; esac\nexit 0\n'))
        result=self.run_launcher('up');self.assertEqual(result.returncode,0,result.stderr)
        calls=self.log.read_text()
        self.assertLess(calls.index('create assets'),calls.index('up --no-build -d'))
        self.assertLess(calls.index('cat /data/state/DuneServer/last-url.txt'),calls.index('run --rm assets'))
        self.assertIn('You can open the link above',result.stdout)

    def test_custom_console_project_does_not_change_the_official_asset_volume(self):
        self.env['COMPOSE_PROJECT_NAME']='separate-console'
        result=self.run_launcher('up')
        self.assertEqual(result.returncode,0,result.stderr)
        asset_calls=[line for line in self.log.read_text().splitlines() if 'compose.assets.yaml' in line]
        self.assertTrue(asset_calls)
        self.assertTrue(all('compose -p dst-docker-assets -f packaging/docker/compose.assets.yaml' in line for line in asset_calls))

    def test_game_download_failure_reports_that_the_web_ui_remains_running(self):
        docker=Path(self.env['PATH'].split(':')[0])/'docker'
        docker.write_text(docker.read_text().replace('exit 0\n','case "$*" in *"--entrypoint python3 assets"*|*"run --rm assets"*) exit 1;; esac\nexit 0\n'))
        result=self.run_launcher('up');self.assertNotEqual(result.returncode,0)
        self.assertIn('Web UI is still running',result.stderr)
        self.assertNotIn(' down',self.log.read_text())
