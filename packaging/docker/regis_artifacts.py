"""Build owned Tank images through fixed Docker operations, never a game entrypoint."""
import copy
import io
import json
import os
from pathlib import Path
import re
import tarfile
import time
from urllib.parse import quote
import uuid

from engine import EngineConnection, EngineError
from regis_job import BUILDS, OVERLAY, OVERLAY_HASHES, digest, validate_recipe

TOOLS_IMAGE = 'dst-docker-regis-tools:local'
SERIALIZER = 'bee2f9b630ac679012c00dde0306eadcc8f21e2b'
RECIPES = Path('/opt/dst-manager/regis-recipes')
BINARY = 'home/dune/server/DuneSandbox/Binaries/Linux/DuneSandboxServer-Linux-Shipping'
PAKS = 'home/dune/server/DuneSandbox/Content/Paks/'


def official_layer_config(base):
    result = {key: copy.deepcopy(value) for key, value in base['Config'].items() if key not in {'Image', 'Labels', 'HostConfig'}}
    # Explicit nulls clear the scratch defaults even when OCI omits the keys.
    for key in ('User', 'Entrypoint', 'Cmd', 'Healthcheck'):
        result.setdefault(key, None)
    return result


def accepted_source(engine, official, recipes=RECIPES):
    match = re.fullmatch(r'registry\.funcom\.com/funcom/self-hosting/seabass-server:([0-9]+)-0-shipping', official)
    if not match or match[1] not in BUILDS:
        raise ValueError('This installed game image has no accepted Tank recipe.')
    build = match[1]
    recipe = json.loads((recipes / (build + '.json')).read_text())
    validate_recipe(recipe, build)
    if recipe.get('baseImage') != official or not re.fullmatch(r'sha256:[a-f0-9]{64}', recipe.get('baseDigest', '')):
        raise ValueError('The accepted Tank base-image recipe is invalid.')
    image = engine.request('GET', '/images/' + quote(official, safe='') + '/json')
    expected = 'registry.funcom.com/funcom/self-hosting/seabass-server@' + recipe['baseDigest']
    if expected not in image.get('RepoDigests', []) or image.get('Architecture') != 'amd64' or image.get('Os') != 'linux' or image['Config'].get('Volumes'):
        raise ValueError('The installed official image identity does not match the accepted Tank recipe.')
    return recipe, image


def inspect_compatibility_image(engine, project, official, identifier, recipes=RECIPES):
    if not re.fullmatch(r'[a-f0-9]{32}', project) or not re.fullmatch(r'sha256:[a-f0-9]{64}', identifier):
        raise ValueError('Invalid owned Tank image identity.')
    recipe, base = accepted_source(engine, official, recipes)
    image = engine.request('GET', '/images/' + quote(identifier, safe='') + '/json')
    labels = image.get('Config', {}).get('Labels') or {}
    expected = {'io.dst.managed': 'true', 'io.dst.project': project, 'io.dst.component': 'regis-image',
                'io.dst.regis.base': base['Id'], 'io.dst.regis.build': recipe['build'],
                'io.dst.regis.binary': recipe['patchedExecutableSha256']}
    layers, previous = image.get('RootFS', {}).get('Layers', []), base.get('RootFS', {}).get('Layers', [])
    if (image.get('Id') != identifier or any(labels.get(key) != value for key, value in expected.items())
            or image.get('Architecture') != 'amd64' or image.get('Os') != 'linux'
            or len(layers) != len(previous) + 1 or layers[:-1] != previous or image['Config'].get('Volumes')
            or (image['Config'].get('User') or '') != (base['Config'].get('User') or '')
            or any((image['Config'].get(key) or []) != (base['Config'].get(key) or []) for key in ('Entrypoint', 'Cmd'))
            or any(image['Config'].get(key) != base['Config'].get(key) for key in ('Env', 'WorkingDir', 'Healthcheck'))):
        raise ValueError('The Tank image does not belong to this world and accepted official base.')
    return image


def checked_report(work, recipe):
    report = work / 'report.json'
    if report.is_symlink() or not report.is_file() or report.stat().st_size > 32768:
        raise ValueError('Tank preparation did not produce a valid success report.')
    data = json.loads(report.read_text())
    expected = {'DuneSandboxServer-Linux-Shipping': recipe['patchedExecutableSha256']}
    expected.update({OVERLAY + '.' + extension: value for extension, value in OVERLAY_HASHES.items()})
    if data.get('ok') is not True or data.get('build') != recipe['build'] or not isinstance(data.get('files'), dict) or set(data['files']) != set(expected):
        raise ValueError('The Tank preparation report does not match the accepted recipe.')
    output = work / 'output'
    if output.is_symlink() or not output.is_dir():
        raise ValueError('Tank preparation output is unavailable.')
    for name, expected_hash in expected.items():
        item, path = data['files'][name], output / name
        if (not isinstance(item, dict) or item.get('sha256') != expected_hash
                or type(item.get('bytes')) is not int or not 0 < item['bytes'] <= 1024**3
                or path.is_symlink() or not path.is_file() or path.stat().st_size != item['bytes']
                or digest(path) != expected_hash):
            raise ValueError('A generated Tank file failed independent verification.')
    return data


class Builder:
    def __init__(self, state, engine, root, persist, recipes=RECIPES):
        self.state, self.engine, self.root, self.persist, self.recipes = state, engine, root, persist, recipes
        self.project = state['id']
        if not re.fullmatch(r'[a-f0-9]{32}', self.project) or root.is_symlink():
            raise ValueError('Invalid Tank preparation storage.')
        self.official = state['worldPlan']['images']['game']['image']
        self.recipe, self.base = accepted_source(engine, self.official, recipes)
        self.tools = engine.request('GET', '/images/' + quote(TOOLS_IMAGE, safe='') + '/json')
        labels = self.tools.get('Config', {}).get('Labels') or {}
        if (labels.get('io.dst.regis-tools') != 'true' or labels.get('io.dst.regis-serializer') != SERIALIZER
                or self.tools.get('Architecture') != 'amd64' or self.tools.get('Os') != 'linux' or self.tools['Config'].get('Volumes')):
            raise ValueError('The packaged Linux Tank tools are unavailable. Run the current Docker installer before enabling Tanks.')

    def save(self, phase):
        self.preparation['phase'] = phase
        self.state['operation']['message'] = 'Tank compatibility: ' + phase.replace('-', ' ')
        self.persist(self.state)

    def labels(self, component):
        return {'io.dst.managed': 'true', 'io.dst.project': self.project, 'io.dst.component': component,
                'io.dst.regis.operation': self.preparation['id']}

    def observed(self, identifier, component):
        result = self.engine.assert_owned(identifier, self.project, component)
        if result.get('Config', {}).get('Labels', {}).get('io.dst.regis.operation') != self.preparation['id']:
            raise ValueError('The recorded Tank utility belongs to another operation.')
        return result

    def scratch(self, role, image, readonly=True, extra=None):
        component = 'regis-' + role
        name = 'dst-' + self.project + '-' + component + '-' + self.preparation['id'][:12]
        found = self.engine.request('GET', '/containers/' + name + '/json', expected=(200, 404))
        if found:
            found = self.observed(found['Id'], component)
            if found.get('Image') != image:
                raise ValueError('The recorded Tank utility image changed.')
            return found['Id']
        spec = {'Image': image, 'User': '1000:10001', 'Labels': self.labels(component), 'Entrypoint': ['/bin/true'], 'Cmd': [],
                'Healthcheck': {'Test': ['NONE']}, 'HostConfig': {
                    'NetworkMode': 'none', 'ReadonlyRootfs': readonly, 'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'],
                    'Memory': 512 * 1024**2, 'MemorySwap': 512 * 1024**2, 'CpuPeriod': 100000, 'CpuQuota': 100000,
                    'PidsLimit': 128, 'RestartPolicy': {'Name': 'no'}}}
        if extra:
            spec.update({key: value for key, value in extra.items() if key != 'HostConfig'})
            spec['HostConfig'].update(extra.get('HostConfig', {}))
        return self.engine.request('POST', '/containers/create?name=' + name, spec)['Id']

    def put(self, identifier, component, data):
        observed = self.observed(identifier, component)
        if observed['State']['Status'] != 'created' or observed.get('Mounts'):
            raise ValueError('Only a new mount-free Tank image layer may receive generated files.')
        connection = EngineConnection(); connection.timeout = 180
        try:
            connection.request('PUT', '/containers/' + identifier + '/archive?path=/', data,
                               {'Content-Type': 'application/x-tar'}, encode_chunked=True)
            response = connection.getresponse(); response.read(65536)
            if response.status != 200: raise EngineError('The owned Tank image layer could not be prepared.')
        finally:
            connection.close()

    def utility(self):
        if self.preparation.get('utilityImage'):
            image = self.engine.request('GET', '/images/' + quote(self.preparation['utilityImage'], safe='') + '/json')
            labels = image.get('Config', {}).get('Labels') or {}
            if (any(labels.get(key) != value for key, value in self.labels('regis-utility-image').items())
                    or labels.get('io.dst.regis.base') != self.base['Id'] or labels.get('io.dst.regis.tools') != self.tools['Id']
                    or image.get('RootFS', {}).get('Layers', [])[:-1] != self.base['RootFS']['Layers']
                    or image['Config'].get('Volumes') or image['Config'].get('User') != '1000:10001'
                    or image['Config'].get('Entrypoint') != ['/usr/bin/python3', '-B', '/tools/regis_job.py']):
                raise ValueError('The recorded Tank utility image needs review.')
            return self.preparation['utilityImage']
        reader = self.scratch('tools-reader', self.tools['Id'])
        layer = self.scratch('tools-layer', self.base['Id'], readonly=False)
        source = EngineConnection(); source.timeout = 180
        try:
            observed = self.observed(reader, 'regis-tools-reader')
            if observed['State']['Status'] != 'created' or observed.get('Mounts'):
                raise ValueError('Tank tools must come from a new mount-free reader.')
            source.request('GET', '/containers/' + reader + '/archive?path=/tools')
            archive = source.getresponse()
            if archive.status != 200: raise EngineError('The packaged Tank tools could not be read.')
            self.put(layer, 'regis-tools-layer', archive)
        finally:
            source.close()
        directory = io.BytesIO()
        with tarfile.open(fileobj=directory, mode='w') as archive:
            member = tarfile.TarInfo('work'); member.type = tarfile.DIRTYPE
            member.uid = 1000; member.gid = 10001; member.mode = 0o750; archive.addfile(member)
        self.put(layer, 'regis-tools-layer', io.BytesIO(directory.getvalue()))
        config = copy.deepcopy(self.base['Config'])
        config.update(User='1000:10001', Entrypoint=['/usr/bin/python3', '-B', '/tools/regis_job.py'], Cmd=[self.recipe['build']],
                      WorkingDir='/work', Healthcheck={'Test': ['NONE']})
        config['Labels'] = {**(config.get('Labels') or {}), **self.labels('regis-utility-image'),
                            'io.dst.regis.base': self.base['Id'], 'io.dst.regis.tools': self.tools['Id']}
        config['Env'] = [value for value in config.get('Env', []) if value.split('=', 1)[0] not in {'HOME', 'LD_LIBRARY_PATH', 'DOTNET_SYSTEM_GLOBALIZATION_INVARIANT'}]
        config['Env'] += ['HOME=/work', 'LD_LIBRARY_PATH=/tools/native', 'DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1']
        image = self.engine.request('POST', '/commit?container=' + layer + '&repo=dst-' + self.project + '-regis-utility&tag=' + self.preparation['id'] + '&pause=false', config, timeout=180)['Id']
        self.preparation['utilityImage'] = image; self.save('tools-ready')
        return image

    def project_volume(self):
        own = self.engine.inspect(os.environ['HOSTNAME'])
        labels = own.get('Config', {}).get('Labels') or {}
        compose = labels.get('com.docker.compose.project')
        mounts = [row for row in own.get('Mounts', []) if row.get('Destination') == '/projects' and row.get('Type') == 'volume']
        if labels.get('com.docker.compose.service') != 'manager' or not compose or len(mounts) != 1:
            raise ValueError('The private manager storage identity could not be verified.')
        volume = self.engine.request('GET', '/volumes/' + quote(mounts[0]['Name'], safe=''))
        labels = volume.get('Labels') or {}
        if labels.get('com.docker.compose.project') != compose or labels.get('com.docker.compose.volume') != 'dst-projects':
            raise ValueError('Tank preparation storage does not belong to this installation.')
        return mounts[0]['Name']

    def wait(self, identifier, component, timeout=300):
        deadline = time.monotonic() + timeout
        while True:
            observed = self.observed(identifier, component)
            if observed['State']['Status'] == 'exited':
                if observed['State']['ExitCode'] != 0:
                    raise ValueError('The isolated Tank preparation failed. Existing game images and Saved files were left unchanged.')
                return
            if time.monotonic() >= deadline:
                raise ValueError('Tank preparation is still pending. Retry the Tank change after the utility finishes; do not start the world yet.')
            time.sleep(0.5)

    def prepare(self):
        previous = self.state.get('regisPreparation')
        if previous:
            if previous.get('project') != self.project or not re.fullmatch(r'[a-f0-9]{32}', previous.get('id', '')):
                raise ValueError('The recorded Tank preparation identity needs review.')
            if previous.get('job'):
                found = self.engine.request('GET', '/containers/' + quote(previous['job'], safe='') + '/json', expected=(200, 404))
                if found:
                    observed = self.engine.assert_owned(previous['job'], self.project, 'regis-generate')
                    if observed['Config']['Labels'].get('io.dst.regis.operation') != previous['id']:
                        raise ValueError('The previous Tank utility belongs to another operation.')
                    failed = observed['State']['Status'] == 'exited' and observed['State']['ExitCode'] != 0
                    if previous.get('phase') == 'failed' and observed['State']['Status'] not in {'created', 'exited'}:
                        raise ValueError('The previous Tank utility is still running. Let it finish before retrying.')
                else:
                    failed = previous.get('phase') != 'verified'
                if failed or previous.get('phase') == 'failed':
                    self.state.setdefault('regisPreparationHistory', []).append(copy.deepcopy(previous))
                    previous = None
        if previous and previous.get('baseImage') == self.base['Id'] and previous.get('toolsImage') == self.tools['Id']:
            self.preparation = previous
            if previous.get('phase') == 'verified':
                inspect_compatibility_image(self.engine, self.project, self.official, previous['image'], self.recipes)
                return previous['image']
        else:
            if previous and previous.get('job'):
                observed = self.engine.assert_owned(previous['job'], self.project, 'regis-generate')
                if observed['State']['Status'] not in {'created', 'exited'}:
                    raise ValueError('The previous Tank utility is still running. Let it finish before preparing different tools or game content.')
            self.preparation = {'id': uuid.uuid4().hex, 'project': self.project, 'baseImage': self.base['Id'], 'toolsImage': self.tools['Id'], 'build': self.recipe['build'], 'startedAt': time.time()}
            self.state['regisPreparation'] = self.preparation
        if self.preparation.get('project') != self.project or not re.fullmatch(r'[a-f0-9]{32}', self.preparation.get('id', '')):
            raise ValueError('The recorded Tank preparation identity needs review.')
        parent = self.root / 'regis-builds'
        if parent.is_symlink(): raise ValueError('Tank preparation storage must not be a symbolic link.')
        parent.mkdir(mode=0o750, exist_ok=True)
        self.work = parent / self.preparation['id']
        if self.work.is_symlink(): raise ValueError('Tank preparation storage must not be a symbolic link.')
        # The capability-dropped manager may assign its existing DST group,
        # never another UID. The isolated helper uses that group for output.
        self.work.mkdir(mode=0o770, exist_ok=True)
        if self.work.stat().st_uid == os.getuid():
            os.chown(self.work, -1, 10001); self.work.chmod(0o770)
        elif self.work.stat().st_uid != 1000 or self.work.stat().st_gid != 10001 or self.work.stat().st_mode & 0o050 != 0o050:
            raise ValueError('The previous Tank preparation directory has unexpected permissions.')
        volume = self.project_volume()
        self.save('preparing-tools')
        utility = self.utility()
        job = self.scratch('generate', utility, extra={'Entrypoint': ['/usr/bin/python3', '-B', '/tools/regis_job.py'], 'Cmd': [self.recipe['build']], 'HostConfig': {
            'Memory': 2 * 1024**3, 'MemorySwap': 2 * 1024**3, 'CpuQuota': 200000,
            'Mounts': [{'Type': 'volume', 'Source': volume, 'Target': '/work', 'VolumeOptions': {'Subpath': 'regis-builds/' + self.preparation['id'], 'NoCopy': True}}],
            'Tmpfs': {'/tmp': 'rw,nosuid,noexec,size=128m,uid=1000,gid=1000'}}})
        self.preparation['job'] = job; self.save('generating-files')
        observed = self.observed(job, 'regis-generate')
        if observed['State']['Status'] == 'created': self.engine.lifecycle(job, self.project, 'start')
        self.wait(job, 'regis-generate')
        report = checked_report(self.work, self.recipe)
        self.save('building-image')
        # Docker commit inherits empty config fields from its container. Keep
        # this never-started layer's runtime config identical to the official
        # base, rather than accidentally committing the scratch /bin/true.
        original_config = official_layer_config(self.base)
        layer = self.scratch('image-layer', self.base['Id'], readonly=False, extra=original_config)
        image = self.preparation.get('candidateImage')
        if not image:
            # Keep the controller's tar outside the helper's writable subpath.
            context = parent / (self.preparation['id'] + '.layer.tar')
            if context.is_symlink(): raise ValueError('The Tank image layer must not be a symbolic link.')
            with tarfile.open(context, mode='w') as archive:
                for name, details in report['files'].items():
                    target = BINARY if name == 'DuneSandboxServer-Linux-Shipping' else PAKS + name
                    member = tarfile.TarInfo(target); member.uid = member.gid = 1000
                    member.mode = 0o755 if target == BINARY else 0o644; member.size = details['bytes']
                    with (self.work / 'output' / name).open('rb') as source: archive.addfile(member, source)
            with context.open('rb') as data: self.put(layer, 'regis-image-layer', data)
            config = copy.deepcopy(self.base['Config'])
            config['Labels'] = {**(config.get('Labels') or {}), **self.labels('regis-image'), 'io.dst.regis.base': self.base['Id'],
                                'io.dst.regis.build': self.recipe['build'], 'io.dst.regis.binary': self.recipe['patchedExecutableSha256']}
            image = self.engine.request('POST', '/commit?container=' + layer + '&repo=dst-' + self.project + '-regis-tanks&tag=' + self.recipe['build'] + '-native1&pause=false', config, timeout=180)['Id']
            self.preparation['candidateImage'] = image; self.save('image-ready')
        inspect_compatibility_image(self.engine, self.project, self.official, image, self.recipes)
        verify = self.scratch('verify', image, extra={'Entrypoint': ['/usr/bin/sha256sum'], 'Cmd': ['/' + (BINARY if name == 'DuneSandboxServer-Linux-Shipping' else PAKS + name) for name in report['files']]})
        self.preparation['verificationJob'] = verify; self.save('verifying-image')
        observed = self.observed(verify, 'regis-verify')
        if observed['State']['Status'] == 'created': self.engine.lifecycle(verify, self.project, 'start')
        self.wait(verify, 'regis-verify', timeout=120)
        raw = bytearray()
        for chunk in self.engine.iter_logs(verify, self.labels('regis-verify')):
            if len(raw) + len(chunk) > 65536: raise ValueError('Tank image verification output was invalid.')
            raw.extend(chunk)
        # Docker log timestamps precede each fixed sha256sum result.
        hashes = dict((path, value) for value, path in re.findall(rb'([a-f0-9]{64})  (/[^\r\n]+)', raw))
        expected = {('/' + (BINARY if name == 'DuneSandboxServer-Linux-Shipping' else PAKS + name)).encode(): details['sha256'].encode() for name, details in report['files'].items()}
        if hashes != expected: raise ValueError('The prepared Tank image contents did not pass verification.')
        self.preparation.update(image=image, finishedAt=time.time()); self.save('verified')
        return image
