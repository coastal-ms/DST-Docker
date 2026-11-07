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
        docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$DST_FIXTURE_DOCKER_LOG"\nexit 0\n');docker.chmod(0o755)
        self.env={**os.environ,'PATH':str(commands)+':'+os.environ['PATH'],'DST_FIXTURE_DOCKER_LOG':str(self.log)}
        self.env.pop('DST_HTTPS_OVERRIDE',None)
        self.releases=[]
        for name in ('a'*64,'b'*64):
            release=self.prefix/'releases'/name;(release/'bin').mkdir(parents=True)
            shutil.copy(Path(__file__).parents[2]/'bin/dst-docker',release/'bin/dst-docker')
            (release/'compose.yaml').write_text('name: fixture\nservices: {}\n')
            self.releases.append(release)
        self.override=self.prefix/'https.compose.json'
        self.override.write_text(json.dumps({'x-dst-https-origin':'https://192.0.2.1:8443','services':{}}))

    def tearDown(self):self.temp.cleanup()

    def run_launcher(self,*args,release=0):
        return subprocess.run(['sh',str(self.releases[release]/'bin/dst-docker'),*args],env=self.env,capture_output=True,text=True)

    def test_installer_upgrade_reuses_same_tls_override_outside_both_releases(self):
        for index in (0,1):
            result=self.run_launcher('status',release=index);self.assertEqual(result.returncode,0,result.stderr)
        lines=self.log.read_text().splitlines()
        self.assertEqual(sum('-f '+str(self.override)+' ps' in line for line in lines),2)
        self.assertEqual(json.loads(self.override.read_text())['x-dst-https-origin'],'https://192.0.2.1:8443')

    def test_repeated_https_reuses_config_and_only_recreates_management_services(self):
        before=self.override.read_bytes()
        result=self.run_launcher('https','192.0.2.1');self.assertEqual(result.returncode,0,result.stderr)
        calls=self.log.read_text()
        self.assertIn('up --no-build -d --no-deps dst https',calls)
        self.assertNotIn('volume create',calls);self.assertNotIn(' pull ',calls)
        self.assertEqual(self.override.read_bytes(),before)

    def test_changed_address_and_http_port_are_refused_without_service_changes(self):
        for args in (('https','192.0.2.2'),('port','9090'),('up','--port','9090')):
            result=self.run_launcher(*args);self.assertNotEqual(result.returncode,0)
        if self.log.exists():self.assertNotIn('up --no-build',self.log.read_text())
