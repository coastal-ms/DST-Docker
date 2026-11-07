import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('dst_https',Path(__file__).with_name('https.py'))
tls=importlib.util.module_from_spec(spec);spec.loader.exec_module(tls)


class HttpsTests(unittest.TestCase):
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
        config=tls.compose_override('dst','https://192.0.2.1:8443')
        app=config['services']['dst'];proxy=config['services']['https']
        self.assertNotIn('DST_HTTP_BIND_ADDRESS',app['environment'])
        self.assertEqual(app['volumes'],['dst-https-config:/run/dst-tls:ro'])
        self.assertNotIn('build',proxy)
        self.assertEqual(proxy['user'],'10001:10001')
        self.assertNotIn('/var/run/docker.sock',json.dumps(config))
        self.assertNotIn('secret',json.dumps(config))

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
