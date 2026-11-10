"""Stage official updates without replacing any live package or game resource."""
from pathlib import Path
import json
import os
import re
import time
import uuid
from assets import package_inventory, MISSING_CONFIGURATION
from asset_version import installed_version
from world_template import read_template

ASSETS = Path('/assets')


def check_headroom(assets=ASSETS, meminfo=Path('/proc/meminfo')):
    counters={line.split(':',1)[0]:line.split(':',1)[1].strip().split()[0] for line in meminfo.read_text().splitlines()}
    if int(counters['MemAvailable'])*1024 < 4*1024**3:
        raise ValueError('Staging an update needs 2 GiB for SteamCMD plus 2 GiB of free host headroom.')
    installed=json.loads((assets/'install-state.json').read_text())
    package_bytes=sum(int(row['bytes']) for row in installed['images'])
    if package_bytes <= 0: raise ValueError('The current official package size could not be verified.')
    capacity=os.statvfs(assets)
    # Steam's temporary download/decompression data can exceed the final
    # archives. This is a minimum admission check, not a size guarantee.
    required=2*package_bytes+1024**3
    if capacity.f_bavail*capacity.f_frsize < required:
        raise ValueError('There is insufficient free disk space to stage a separate official update package.')


def start_stage(state, engine, expected_build, save):
    if not isinstance(expected_build, str) or not re.fullmatch(r'[0-9]{1,18}', expected_build):
        raise ValueError('Choose a valid official update build.')
    if state.get('assetUpdate'):
        previous = state['assetUpdate']
        if previous['expectedBuild'] == expected_build and previous['phase'] in {'downloading', 'ready'}:
            return {'stageId': previous['id'], 'expectedBuild': expected_build}
        raise ValueError('Review the existing staged update before preparing another package.')
    own = engine.inspect(os.environ['HOSTNAME'])
    mounts = [row for row in own.get('Mounts', []) if row.get('Destination') == '/assets' and row.get('Type') == 'volume']
    if len(mounts) != 1: raise ValueError('Official asset storage could not be identified.')
    check_headroom()
    record = {'id': uuid.uuid4().hex, 'expectedBuild': expected_build, 'phase': 'preparing', 'startedAt': time.time()}
    state['assetUpdate'] = record;save(state)
    record['job'] = engine.create_asset_stage_job(state['id'], record['id'], expected_build, mounts[0]['Name'])
    save(state)
    engine.lifecycle(record['job'], state['id'], 'start')
    record['phase'] = 'downloading';save(state)
    return {'stageId': record['id'], 'expectedBuild': expected_build}


def observe_stage(state, engine, assets=ASSETS):
    record = state.get('assetUpdate')
    if not record: return None, False
    changed = False
    if record.get('job') and record['phase'] in {'preparing', 'downloading'}:
        owned = engine.assert_owned(record['job'], state['id'], 'asset-stage')
        if owned.get('Config', {}).get('Labels', {}).get('io.dst.stage') != record['id']:
            raise ValueError('Staged update job identity could not be verified.')
        if owned.get('State', {}).get('Status') == 'exited':
            changed = True;record['finishedAt'] = time.time()
            try:
                if owned['State'].get('ExitCode') != 0: raise ValueError('Download failed.')
                if not re.fullmatch(r'[a-f0-9]{32}', record['id']): raise ValueError('Invalid stage.')
                root = assets / 'staged' / record['id']
                report = json.loads((root / 'install-state.json').read_text())
                version = installed_version(root / 'server/steamapps/appmanifest_4754530.acf')
                if report.get('state') != 'downloaded' or version['installedBuild'] != record['expectedBuild']:
                    raise ValueError('Unexpected package build.')
                inventory = package_inventory(root / 'server')
                if inventory != report.get('images'): raise ValueError('Package inventory changed.')
                template = read_template(root / 'server/scripts/setup/templates/world-template.yaml')
                record.update(phase='ready', installedBuild=version['installedBuild'], templateSha256=template['sha256'], images=inventory)
            except Exception:
                message = 'The staged official package failed download or validation. The active installation was left unchanged.'
                # Only this fixed installer message is safe for the public status.
                try:
                    failure = json.loads((assets / 'staged' / record['id'] / 'install-state.json').read_text())
                    if failure.get('error') == MISSING_CONFIGURATION:
                        message = MISSING_CONFIGURATION
                except (OSError, ValueError):
                    pass
                record.update(phase='failed', error=message)
    return {key: record[key] for key in ('id', 'phase', 'expectedBuild', 'installedBuild', 'startedAt', 'finishedAt', 'error', 'templateSha256') if key in record}, changed
