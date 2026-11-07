#!/usr/bin/env python3
"""Prepare an optional private-IP HTTPS front end. Never installs client trust."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import secrets
import ssl
import subprocess

# Official Caddy Linux amd64 image; this edition's game runtime is amd64.
CADDY = 'caddy@sha256:fc9cbc100585871d18d4e451cca7021785c90a7006087427ae5ceb3e4efe6424'


def docker(*args, input=None):
    result = subprocess.run(['docker', *args], input=input, text=True, capture_output=True)
    if result.returncode:
        # Do not echo config stdin or expanded proxy secrets on failure.
        raise RuntimeError('Docker HTTPS setup command failed: ' + ' '.join(args[:3]))
    return result.stdout


def validate(project, address, port, upstream_port):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', project):
        raise ValueError('Use the existing Compose project name (lowercase letters, digits, hyphens).')
    ip = ipaddress.ip_address(address)
    if ip.version != 4 or ip.is_unspecified or ip.is_multicast:
        raise ValueError('Choose a specific IPv4 address of the Docker host.')
    if not all(1024 <= p <= 65535 for p in (port, upstream_port)) or port == upstream_port:
        raise ValueError('HTTPS and the existing HTTP console need different ports, from 1024 to 65535.')
    return str(ip)


def configuration(address, port, upstream_port, secret):
    origin = f'https://{address}:{port}'
    caddy = f'''{{
    admin off
    persist_config off
    skip_install_trust
    auto_https disable_redirects
    servers {{
        protocols h1 h2
    }}
}}
{origin} {{
    bind {address}
    tls internal
    reverse_proxy 127.0.0.1:{upstream_port} {{
        header_up Host {address}:{port}
        header_up X-Dst-Tls-Proxy {secret}
        header_up X-Forwarded-Proto https
        header_up -Cf-Access-Authenticated-User-Email
        header_up -Cf-Access-Jwt-Assertion
        header_up -Cf-Connecting-Ip
        header_up -Cf-Ray
        header_up -X-Dune-Bridge-Protocol
        header_up -X-Dune-Original-Authority
        header_up -X-Dune-Bridge-Proof
    }}
}}
'''
    return {'Caddyfile': caddy, 'proxy.json': json.dumps({'origin': origin, 'secret': secret})}


def compose_override(project, origin):
    # JSON is also valid YAML. No secret or private key is written on the host.
    return {
        'x-dst-https-origin': origin,
        'services': {
            'dst': {
                'environment': {'DST_TLS_PROXY_CONFIG': '/run/dst-tls/proxy.json'},
                'volumes': ['dst-https-config:/run/dst-tls:ro'],
            },
            'https': {
                'image': CADDY, 'network_mode': 'host', 'user': '10001:10001',
                'restart': 'no', 'init': True, 'read_only': True,
                'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
                'command': ['caddy', 'run', '--config', '/run/dst-tls/Caddyfile', '--adapter', 'caddyfile'],
                'environment': {'XDG_DATA_HOME': '/data', 'XDG_CONFIG_HOME': '/tmp/caddy-config'},
                'tmpfs': ['/tmp:rw,noexec,nosuid,size=32m,uid=10001,gid=10001'],
                'volumes': ['dst-https-config:/run/dst-tls:ro', 'dst-https-data:/data'],
            },
        },
        'volumes': {
            name: {'external': True, 'name': project + '-' + name}
            for name in ('dst-https-config', 'dst-https-data')
        },
    }


def prepare(args):
    address = validate(args.project, args.address, args.port, args.upstream_port)
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError('The override already exists. Reuse it; do not replace an existing authority.')
    names = [args.project + '-' + n for n in ('dst-https-config', 'dst-https-data')]
    existing = set(docker('volume', 'ls', '--format', '{{.Name}}').splitlines())
    if existing.intersection(names):
        raise ValueError('HTTPS volumes already exist. Preserve them and reuse the original override.')
    docker('pull', CADDY)
    files = configuration(address, args.port, args.upstream_port, secrets.token_hex(32))
    for name in names:
        docker('volume', 'create', '--label', 'com.dst.https.project=' + args.project, name)
    # Dedicated new volumes only. No project, Saved, config, or Docker socket mount.
    payload = json.dumps(files)
    init = '''import json,os,pathlib,sys
files=json.load(sys.stdin)
for base in ('/tls-config','/tls-data'):
 p=pathlib.Path(base);p.chmod(0o700)
for name,value in files.items():
 p=pathlib.Path('/tls-config')/name;p.write_text(value);p.chmod(0o600);os.chown(p,10001,10001)
for base in ('/tls-config','/tls-data'):os.chown(base,10001,10001)
'''
    docker('run', '--rm', '-i', '--network', 'none', '--read-only', '--user', '0',
           '--cap-drop', 'ALL', '--cap-add', 'CHOWN', '--security-opt', 'no-new-privileges:true',
           '-v', names[0] + ':/tls-config', '-v', names[1] + ':/tls-data',
           '--entrypoint', 'python3', args.app_image, '-c', init, input=payload)
    # Syntax/TLS policy validation before any service is restarted.
    docker('run', '--rm', '--network', 'none', '--read-only', '--user', '10001:10001',
           '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
           '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m,uid=10001,gid=10001',
           '-e', 'XDG_DATA_HOME=/tmp/data', '-e', 'XDG_CONFIG_HOME=/tmp/config',
           '-v', names[0] + ':/run/dst-tls:ro', '--entrypoint', 'caddy', CADDY,
           'validate', '--config', '/run/dst-tls/Caddyfile', '--adapter', 'caddyfile')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as f:
        json.dump(compose_override(args.project, f'https://{address}:{args.port}'), f, indent=2)
        f.write('\n')
    print(json.dumps({'override': str(output), 'url': f'https://{address}:{args.port}',
                      'servicesStarted': False, 'clientTrustInstalled': False}))


def export(args):
    validate(args.project, '127.0.0.1', 8443, 8088)
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError('Choose a new public certificate output path; the existing file is preserved.')
    labels=json.loads(docker('volume','inspect','--format','{{json .Labels}}',args.project+'-dst-https-data')) or {}
    if labels.get('com.dst.https.project')!=args.project:
        raise ValueError('The HTTPS authority volume does not belong to this setup.')
    pem = docker('run', '--rm', '--network', 'none', '--read-only', '--user', '10001:10001',
                 '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                 '-v', args.project + '-dst-https-data:/data:ro', '--entrypoint', 'cat', CADDY,
                 '/data/caddy/pki/authorities/local/root.crt')
    der = ssl.PEM_cert_to_DER_cert(pem)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='ascii') as f:
        f.write(pem)
    print(json.dumps({'publicCertificate': str(output), 'sha256': hashlib.sha256(der).hexdigest(),
                      'clientTrustInstalled': False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare', help='Prepare isolated TLS volumes and a Compose override; starts nothing.')
    p.add_argument('--project', required=True)
    p.add_argument('--address', required=True)
    p.add_argument('--port', type=int, default=8443)
    p.add_argument('--upstream-port', type=int, default=8088)
    p.add_argument('--app-image', default='dst-docker:local')
    p.add_argument('--output', required=True)
    e = commands.add_parser('export-root', help='Export only the public CA certificate after HTTPS starts.')
    e.add_argument('--project', required=True)
    e.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        (prepare if args.command == 'prepare' else export)(args)
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
