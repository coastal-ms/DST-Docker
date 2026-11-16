#!/usr/bin/env bash
set -Eeuo pipefail
if ! command -v python3 >/dev/null 2>&1; then
  command -v apt-get >/dev/null 2>&1 || { echo 'Install Python 3, then rerun this command.' >&2; exit 1; }
  if ((EUID == 0)); then apt-get update && apt-get install -y python3;
  else sudo apt-get update && sudo apt-get install -y python3; fi
fi
python3 - "$@" <<'DST_BOOTSTRAP_PY'
import gzip, io, json, os, re, subprocess, sys, tarfile, tempfile, urllib.request, urllib.parse
from pathlib import Path, PurePosixPath

REPO = 'coastal-ms/DST-Docker'
API = 'https://api.github.com/repos/' + REPO

class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if result and urllib.parse.urlparse(req.full_url).netloc != urllib.parse.urlparse(newurl).netloc:
            result.remove_header('Authorization')
        return result

def token():
    value = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if value: return value
    try:
        return subprocess.check_output(['gh', 'auth', 'token', '--hostname', 'github.com'], stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError): return ''

def download(opener, path, auth, limit, timeout=120):
    headers = {'User-Agent': 'DST-Docker-bootstrap', 'Accept': 'application/vnd.github+json'}
    if auth: headers['Authorization'] = 'Bearer ' + auth
    with opener.open(urllib.request.Request(API + path, headers=headers), timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit: raise ValueError('Source download exceeds the supported size.')
    return data

def normalize(data, destination):
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as source:
        members = source.getmembers()
        roots, names, total = set(), set(), 0
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or not (member.isfile() or member.isdir()):
                raise ValueError('Unsupported source archive entry.')
            roots.add(path.parts[0]); total += member.size
            name = '/'.join(path.parts[1:])
            if name in names: raise ValueError('Duplicate source archive entry.')
            names.add(name)
        if len(roots) != 1 or total > 512 * 1024**2 or 'bin/dst-install' not in names:
            raise ValueError('Invalid DST source archive.')
        with destination.open('wb') as output, gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0) as compressed, tarfile.open(fileobj=compressed, mode='w') as target:
            for member in members:
                name = '/'.join(PurePosixPath(member.name).parts[1:])
                if not name: continue
                member.name = name
                target.addfile(member, source.extractfile(member) if member.isfile() else None)
        installer = source.extractfile(next(m for m in members if m.name == 'bin/dst-install'))
        return installer.read()

def main(args):
    opener = urllib.request.build_opener(Redirect())
    auth = token()
    release = json.loads(download(opener, '/releases/latest', auth, 1024**2))
    tag = release['tag_name']
    if not re.fullmatch(r'v\d+\.\d+\.\d+', tag): raise ValueError('Invalid release tag.')
    ref = json.loads(download(opener, '/git/ref/tags/' + tag, auth, 1024**2))['object']
    for _ in range(5):
        if ref.get('type') == 'commit': break
        if ref.get('type') != 'tag' or not re.fullmatch(r'[0-9a-f]{40}', ref.get('sha', '')):
            raise ValueError('Invalid release tag reference.')
        ref = json.loads(download(opener, '/git/tags/' + ref['sha'], auth, 1024**2))['object']
    if ref.get('type') != 'commit': raise ValueError('Release tag must resolve to a commit.')
    commit = ref['sha']
    if not re.fullmatch(r'[0-9a-f]{40}', commit): raise ValueError('Invalid release commit.')
    if os.environ.get('DST_EXPECTED_RELEASE_TAG') and (tag != os.environ['DST_EXPECTED_RELEASE_TAG'] or commit != os.environ.get('DST_EXPECTED_RELEASE_COMMIT')):
        raise ValueError('The release changed. Check for updates again before installing.')
    print('Installing DST Docker ' + tag + ' from its source release.', flush=True)
    data = download(opener, '/tarball/' + commit, auth, 128 * 1024**2)
    with tempfile.TemporaryDirectory(prefix='dst-bootstrap-') as folder:
        archive = Path(folder) / 'source.tar.gz'
        installer = Path(folder) / 'dst-install'
        installer.write_bytes(normalize(data, archive))
        env = dict(os.environ, task_package_revision=commit, task_product_version=tag[1:])
        return subprocess.call(['bash', str(installer), '--source-archive', str(archive), *args], env=env)

if __name__ == '__main__':
    try: sys.exit(main(sys.argv[1:]))
    except Exception as error:
        print('DST source download failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
DST_BOOTSTRAP_PY
