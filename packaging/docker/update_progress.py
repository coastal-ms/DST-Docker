"""Bounded, read-only progress for the installation's latest server update."""
from pathlib import Path
import re
from log_export import redact

LIMIT = 32768
PHASES = {
    'staging': 'Downloading update', 'validating': 'Checking package',
    'stopping': 'Stopping battlegroup', 'backing-up': 'Creating backup',
    'verifying-backup': 'Verifying backup', 'activating-package': 'Applying package',
    'migrating-schema': 'Updating database', 'preparing-components': 'Preparing maps',
    'preparing-tank-image': 'Preparing Tank support', 'checking-partitions': 'Checking partitions',
    'checking-maps': 'Checking map readiness', 'publishing': 'Restoring connections',
    'committing': 'Finishing update', 'completed': 'Update complete',
    'failed-preflight': 'Update failed before installation', 'recovering': 'Restoring previous version',
    'recovery-required': 'Recovery needed', 'rolled-back': 'Previous version restored',
}


def clean(raw):
    raw = re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]', b'', raw)
    return redact(raw).decode('utf-8', errors='replace').replace('\x00', '')


def file_tail(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Update output is unavailable.')
    with path.open('rb') as stream:
        size = stream.seek(0, 2)
        stream.seek(max(0, size - LIMIT))
        raw = stream.read(LIMIT)
    if size > LIMIT:
        raw = raw.partition(b'\n')[2]
    return clean(raw), size > LIMIT


def snapshot(state, engine, operation_id=None, include_output=False, assets=Path('/assets')):
    if type(include_output) is not bool:
        raise ValueError('Invalid update output option.')
    run = state.get('updateRun')
    if not run:
        return {'available': False}
    current = state.get('operation') or {}
    is_update = current.get('action') in {'updates.apply', 'updates.recover'}
    allowed = {run['id']}
    if is_update:
        allowed.add(current.get('id'))
    if operation_id is not None and (not isinstance(operation_id, str) or not re.fullmatch(r'[a-f0-9]{32}', operation_id) or operation_id not in allowed):
        raise ValueError('The update changed. Refresh its details.')
    phase = run['phase']
    running = is_update and current.get('phase') == 'running'
    status = 'running' if running else 'completed' if phase == 'completed' else 'failed'
    error = run.get('error') or (current.get('error') if is_update else None)
    reply = {'available': True, 'operationId': run['id'], 'build': run.get('build'),
             'phase': phase, 'label': PHASES.get(phase, 'Updating server'), 'status': status,
             'running': running, 'startedAt': run.get('startedAt'), 'finishedAt': run.get('finishedAt'),
             'error': clean(str(error).encode()) if error else None,
             'events': [{'label': PHASES.get(row['phase'], 'Updating server'), 'at': row['at']}
                        for row in run.get('events', [])[-40:]], 'output': []}
    if not include_output:
        return reply

    stage = state.get('assetUpdate') or {}
    stage_id = stage.get('id', '')
    belongs = run.get('stageId') == stage_id or (phase in {'staging', 'failed-preflight'} and stage.get('expectedBuild') == run.get('build') and stage.get('startedAt', 0) >= run.get('startedAt', 0))
    if belongs and re.fullmatch(r'[a-f0-9]{32}', stage_id):
        row = {'name': 'Package download'}
        try:
            directory = assets / 'staged' / stage_id
            if directory.is_symlink() or (assets / 'staged').is_symlink():
                raise ValueError('Invalid update storage.')
            row['text'], row['truncated'] = file_tail(directory / 'steam-install.log')
        except (OSError, ValueError):
            row['error'] = 'Download output is not available yet.'
        reply['output'].append(row)

    backup = state.get('backups', {}).get(run.get('backupId'), {})
    jobs = [('Backup', backup.get('job'), 'db-backup'),
            ('Backup verification', (backup.get('verification') or {}).get('job'), 'db-verify'),
            ('Package installation', run.get('activateJob'), 'asset-switch'),
            ('Database update', run.get('migrationJob'), 'db-migrate'),
            ('Recovery', run.get('rollbackJob'), 'asset-switch')]
    for name, identifier, component in jobs:
        if not identifier:
            continue
        row = {'name': name}
        try:
            labels = {'io.dst.managed': 'true', 'io.dst.project': state['id'], 'io.dst.component': component}
            raw = b''.join(engine.iter_logs(identifier, labels, tail=200, max_bytes=LIMIT))
            row.update(text=clean(raw), truncated=len(raw) >= LIMIT)
        except Exception:
            row['error'] = 'This retained output is unavailable.'
        reply['output'].append(row)
    return reply
