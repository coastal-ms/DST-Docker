import argparse
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('dst_https',Path(__file__).with_name('https.py'))
tls=importlib.util.module_from_spec(spec);spec.loader.exec_module(tls)


class HttpsTests(unittest.TestCase):
    def test_sudo_proxy_metadata_is_readable_by_original_user_and_keeps_existing_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'https.json'
            output.write_text('{"old":true}');output.chmod(0o600)
            with patch('mirror_config.launch_owner',return_value=(65534,65534,Path(temporary))):
                tls.write_override(output,{'new':True},replace=True)
                self.assertEqual(output.stat().st_uid,65534);self.assertEqual(output.stat().st_mode&0o777,0o600)
                self.assertEqual(json.loads(output.read_text()),{'new':True})
                fresh=Path(temporary)/'fresh.json';tls.write_override(fresh,{'new':True})
                self.assertEqual(fresh.stat().st_uid,65534);self.assertEqual(fresh.stat().st_mode&0o777,0o600)
            self.assertEqual(list(Path(temporary).glob('.dst-https-*')),[])
    def test_addresses_and_ports_are_validated_before_any_docker_work(self):
        for address in ('0.0.0.0','224.0.0.1','::1','host\nmalicious','example.com'):
            with self.assertRaises(ValueError):tls.validate('dst-preview',address,8443,8088)
        for project in ('../another','DST','a;id'):
            with self.assertRaises(ValueError):tls.validate(project,'192.0.2.1',8443,8088)
        with self.assertRaises(ValueError):tls.validate('dst','192.0.2.1',8088,8088)
        self.assertEqual(tls.validate('dst','192.0.2.1',8443,8088),'192.0.2.1')

    def test_proxy_replaces_proof_and_scheme_and_removes_other_identity_headers(self):
        config=tls.configuration('192.0.2.1',8443,8088,'a'*64)
        self.assertIn('skip_install_trust',config['Caddyfile'])
        self.assertIn('header_up X-Dst-Tls-Proxy '+'a'*64,config['Caddyfile'])
        self.assertIn('reverse_proxy 127.0.0.1:8088',config['Caddyfile'])
        self.assertIn('header_up -X-Dune-Bridge-Proof',config['Caddyfile'])
        self.assertIn('header_up -Cf-Access-Jwt-Assertion',config['Caddyfile'])
        self.assertEqual(json.loads(config['proxy.json'])['origin'],'https://192.0.2.1:8443')

    def test_override_preserves_http_config_and_keeps_private_authority_away_from_app(self):
        config=tls.compose_override('dst','https://192.0.2.1:8088',18088)
        app=config['services']['dst'];proxy=config['services']['https']
        self.assertEqual(app['environment']['DST_HTTP_BIND_ADDRESS'],'127.0.0.1')
        self.assertEqual(app['environment']['DST_HTTP_INTERNAL_PORT'],'18088')
        self.assertEqual(config['x-dst-https-format'],2)
        self.assertEqual(app['volumes'],['dst-https-config:/run/dst-tls:ro'])
        self.assertNotIn('build',proxy)
        self.assertEqual(proxy['user'],'10001:10001')
        self.assertEqual(proxy['restart'],'unless-stopped')
        self.assertNotIn('/var/run/docker.sock',json.dumps(config))
        self.assertNotIn('secret',json.dumps(config))

    def test_restart_upgrade_preserves_existing_tls_and_custom_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'https.json'
            before=tls.compose_override('dst','https://192.0.2.1:8443',18088)
            before['services']['https']['restart']='no';before['custom']='preserve'
            output.write_text(json.dumps(before))
            args=argparse.Namespace(output=str(output))
            with patch('mirror_config.launch_owner',return_value=(os.getuid(),os.getgid(),Path(temporary))):
                tls.upgrade_restart_policy(args)
            after=json.loads(output.read_text());self.assertEqual(after['services']['https'].pop('restart'),'unless-stopped')
            before['services']['https'].pop('restart');self.assertEqual(after,before)

    def test_prepare_refuses_to_replace_existing_authority_or_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'https.json'
            args=argparse.Namespace(project='dst',address='192.0.2.1',port=8443,upstream_port=8088,output=str(output))
            with patch.object(tls,'docker',return_value='dst-dst-https-data\n') as docker:
                with self.assertRaisesRegex(ValueError,'already exist'):tls.prepare(args)
                self.assertEqual(docker.call_count,1)
            output.write_text('keep')
            with patch.object(tls,'docker') as docker:
                with self.assertRaisesRegex(ValueError,'already exists'):tls.prepare(args)
                docker.assert_not_called()
            self.assertEqual(output.read_text(),'keep')

    def test_export_rejects_other_volume_owners_without_reading_certificate_or_creating_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'root.crt'
            args=argparse.Namespace(project='dst',output=str(output))
            with patch.object(tls,'docker',return_value='{"com.dst.https.project":"other"}') as docker:
                with self.assertRaisesRegex(ValueError,'does not belong'):tls.export(args)
                self.assertEqual(docker.call_count,1)
            self.assertFalse(output.exists())

    def test_update_preserves_authority_and_secret_and_validates_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'https.json'
            output.write_text(json.dumps(tls.compose_override('dst','https://192.0.2.1:8443',18088)))
            args=argparse.Namespace(project='dst',address='192.0.2.1',port=8088,upstream_port=18088,output=str(output),app_image='fixture')
            calls=[]
            def fake(*parts,input=None):
                calls.append((parts,input))
                if parts[:2]==('volume','inspect'):return '{"com.dst.https.project":"dst"}'
                if parts[-1]=='/tls/proxy.json':return json.dumps({'secret':'a'*64})
                return ''
            with patch.object(tls,'docker',side_effect=fake):tls.update(args)
            self.assertEqual(json.loads(output.read_text())['x-dst-https-origin'],'https://192.0.2.1:8088')
            writes=[(parts,payload) for parts,payload in calls if 'python3' in parts]
            self.assertEqual(len(writes),1)
            self.assertIn('a'*64,writes[0][1])
            self.assertFalse(any('dst-dst-https-data:/data' in part for parts,_ in calls for part in parts))
            before=output.read_bytes()
            def fail(*parts,input=None):
                if 'validate' in parts:raise RuntimeError('invalid replacement')
                return fake(*parts,input=input)
            with patch.object(tls,'docker',side_effect=fail):
                with self.assertRaises(RuntimeError):tls.update(args)
            self.assertEqual(output.read_bytes(),before)
