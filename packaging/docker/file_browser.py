"""Run the existing File Browser UI against this world's owned Saved volumes."""
import re
from urllib.parse import quote

IMAGE = 'filebrowser/filebrowser@sha256:a469ea076d4a1b4b1d86a41d130f2f536cd9da996a2b1fb39c0d7635f9d89b9a'


def saved_mounts(state, engine):
    project = state['id']
    if not re.fullmatch(r'[a-f0-9]{32}', project):
        raise ValueError('Invalid file browser world.')
    mounts = []
    for game in state['worldPlan']['games']:
        partition = game['partition']
        component = 'game-' + str(partition)
        entry = state.get('services', {}).get(component)
        if not entry or not entry.get('id') or entry.get('phase') != 'prepared':
            continue
        observed = engine.assert_owned(entry['id'], project, component)
        expected = 'dst-' + project + '-' + component + '-saved'
        saved = [m for m in observed.get('Mounts', []) if m.get('Destination') == '/home/dune/server/DuneSandbox/Saved']
        if len(saved) != 1 or saved[0].get('Type') != 'volume' or saved[0].get('Name') != expected:
            raise ValueError('The game saved files do not belong to this world.')
        volume = engine.request('GET', '/volumes/' + quote(expected, safe=''))
        labels = volume.get('Labels') or {}
        if labels.get('io.dst.project') != project or labels.get('io.dst.managed') != 'true':
            raise ValueError('The game saved volume is not owned.')
        # Each map retains its own Saved files. Every UserSettings view points
        # to the authoritative Hagga Saved/UserSettings directory.
        target = '/srv' if partition == 1 else '/srv/Maps/' + game['map'] + '-' + str(partition)
        mounts.append({'Type': 'volume', 'Source': expected, 'Target': target})
        if partition!=1:
            mounts.append({'Type':'volume','Source':'dst-'+project+'-game-1-saved','Target':target+'/UserSettings',
                           'VolumeOptions':{'Subpath':'UserSettings'}})
    if not any(m['Target'] == '/srv' for m in mounts):
        raise ValueError('Prepare Hagga Basin saved files before the file browser.')
    return mounts


def create(state, engine, mounts):
    project = state['id']
    port = state['profile']['gamePortBase'] + 1005
    network = state['worldPlan']['network']
    if network != 'dst-' + project + '-network' or not 1024 <= port <= 65535:
        raise ValueError('Invalid file browser network or port.')
    labels = engine.request('GET', '/networks/' + network).get('Labels') or {}
    if labels.get('io.dst.project') != project or labels.get('io.dst.managed') != 'true':
        raise ValueError('File Browser network is not owned.')
    image = engine.request('GET', '/images/' + quote(IMAGE, safe='') + '/json')
    if IMAGE not in image.get('RepoDigests', []):
        raise ValueError('Run the Docker launcher to load the pinned File Browser image.')
    storage = 'dst-' + project + '-file-browser'
    engine.ensure_owned_volume(storage, project, 'file-browser')
    mounts = [*mounts, {'Type': 'volume', 'Source': storage, 'Target': '/database'}]
    spec = {
        'Image': IMAGE, 'User': '1000:1000',
        'Labels': {'io.dst.managed': 'true', 'io.dst.project': project, 'io.dst.component': 'file-browser'},
        'Cmd': ['--noauth', '--disableExec=true', '--followExternalSymlinks=false',
                '--root=/srv', '--database=/database/filebrowser.db', '--address=0.0.0.0', '--port=80'],
        'ExposedPorts': {'80/tcp': {}},
        'HostConfig': {
            'NetworkMode': network, 'ReadonlyRootfs': True,
            'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'],
            'Memory': 128 * 1024**2, 'MemorySwap': 128 * 1024**2, 'PidsLimit': 64,
            'PortBindings': {'80/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]},
            'Mounts': mounts,
            'Tmpfs': {'/config': 'rw,nosuid,noexec,size=1m,uid=1000,gid=1000',
                      '/tmp': 'rw,nosuid,noexec,size=16m,uid=1000,gid=1000'},
            'RestartPolicy': {'Name': 'no'},
            'LogConfig': {'Type': 'json-file', 'Config': {'max-size': '2m', 'max-file': '2'}},
        },
    }
    return engine.request('POST', '/containers/create?name=dst-' + project + '-file-browser', spec)['Id']
