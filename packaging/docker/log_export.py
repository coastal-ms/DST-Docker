"""Stream this installation's retained container logs to a browser archive."""
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import quote
import zipfile

EXPORTS = Path('/control/log-exports')
ID = re.compile(r'[a-f0-9]{32}')
MAX_CONTAINER = 128 * 1024 * 1024


def redact(line):
    line = re.sub(rb'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', b'<redacted-token>', line)
    line = re.sub(rb'(?i)((?:password|passwd|auth_token|access_token|service_token|secret)["\s]*[:=]["\s]*)([^\s",;]+)', rb'\1<redacted>', line)
    line = re.sub(rb'(?i)(authorization["\s]*[:=]["\s]*(?:bearer\s+)?)[^\s",;]+', rb'\1<redacted>', line)
    line = re.sub(rb'([?&](?:t|token|key)=)[A-Za-z0-9_.-]+', rb'\1<redacted>', line)
    line = re.sub(rb'(/api/webhooks/[0-9]+/)[A-Za-z0-9_-]+', rb'\1<redacted>', line)
    return re.sub(rb'(?i)((?:postgres(?:ql)?|amqps?)://[^:\s/]+:)[^@\s]+@', rb'\1<redacted>@', line)


def targets(state, engine, scope):
    if scope == 'diagnostics':
        selected = targets(state, engine, 'battlegroup') + targets(state, engine, 'operator')
        return list({entry[1]: entry for entry in selected}.values())
    if scope not in {'battlegroup', 'operator'}:
        raise ValueError('Choose battlegroup or operator logs.')
    project = state['id']
    result = []
    if scope == 'battlegroup':
        entries = [('postgres', state.get('database'))]
        entries += list(state.get('connections', {}).items()) + list(state.get('services', {}).items())
    else:
        entries = [('scaler', state.get('scaler')), ('settings', state.get('settingsService')), ('file-browser', state.get('fileBrowser'))]
        entries += [('map-observer-' + component[5:], entry) for component, entry in state.get('mapObservers', {}).items() if re.fullmatch(r'game-[0-9]+', component)]
        own = engine.inspect(os.environ['HOSTNAME'])
        labels = own.get('Config', {}).get('Labels', {})
        compose = labels.get('com.docker.compose.project', '')
        if labels.get('com.docker.compose.service') != 'manager' or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', compose):
            raise ValueError('The operator installation identity could not be verified.')
        filters = quote(json.dumps({'label': ['com.docker.compose.project=' + compose]}), safe='')
        ordinals = {}
        for row in engine.request('GET', '/containers/json?all=1&filters=' + filters):
            service = row.get('Labels', {}).get('com.docker.compose.service')
            if service in {'dst', 'manager', 'observer'}:
                ordinals[service] = ordinals.get(service, 0) + 1
                result.append(('portal-' + service + '-' + str(ordinals[service]), row['Id'], {'com.docker.compose.project': compose, 'com.docker.compose.service': service}))
    for component, entry in entries:
        if entry and entry.get('id') and re.fullmatch(r'[a-z0-9-]{1,64}', component):
            result.append((component, entry['id'], {'io.dst.managed': 'true', 'io.dst.project': project, 'io.dst.component': component}))
    return result


def export_logs(state, engine, scope, identifier, directory=EXPORTS):
    if not isinstance(identifier, str) or not ID.fullmatch(identifier):
        raise ValueError('Invalid log export identity.')
    selected = targets(state, engine, scope)
    if not selected:
        raise ValueError('No log sources are prepared for this installation.')
    directory.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.chown(directory, -1, 10001)
    # Retain at most three completed downloads. Never follow links or touch
    # unrelated files in the shared control volume.
    previous = sorted((p for p in directory.glob('*.zip') if ID.fullmatch(p.stem) and not p.is_symlink()), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in previous[2:]: old.unlink()
    temporary = directory / (identifier + '.tmp')
    destination = directory / (identifier + '.zip')
    report = {'scope': scope, 'createdAt': time.time(), 'sources': [], 'redaction': 'Known credential fields, connection passwords, JWTs and portal-link credentials are masked.', 'maxBytesPerSource': MAX_CONTAINER}
    try:
        with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            for component, container, labels in selected:
                record = {'component': component, 'bytes': 0, 'truncated': False}
                try:
                    with archive.open(component + '.log', 'w') as output:
                        pending = b''
                        for chunk in engine.iter_logs(container, labels):
                            remaining = MAX_CONTAINER - record['bytes']
                            if len(chunk) > remaining: record['truncated'] = True
                            chunk = chunk[:remaining]
                            record['bytes'] += len(chunk)
                            pending += chunk
                            lines = pending.split(b'\n');pending = lines.pop()
                            for line in lines: output.write(redact(line) + b'\n')
                            if len(pending) > 2 * 1024 * 1024:
                                output.write(b'[Oversized log line omitted]\n');pending=b'';record['truncated']=True
                            if record['bytes'] >= MAX_CONTAINER: record['truncated']=True;break
                        if pending: output.write(redact(pending))
                    record['ok'] = True
                except Exception:
                    record.update(ok=False, error='This source could not be collected. Its container may have been replaced or its log driver may be unavailable.')
                report['sources'].append(record)
            report['complete'] = all(row['ok'] and not row['truncated'] for row in report['sources'])
            if not any(row['ok'] for row in report['sources']):
                raise ValueError('No container logs could be collected; no download was prepared.')
            archive.writestr('export-report.json', json.dumps(report, indent=2))
        with temporary.open('rb') as stream: os.fsync(stream.fileno())
        temporary.chmod(0o640);os.chown(temporary, -1, 10001)
        temporary.replace(destination)
        return {'downloadId': identifier, 'filename': 'DST-' + scope + '-logs.zip', 'complete': report['complete'],
                'sources': len(report['sources']), 'unavailable': sum(not row['ok'] for row in report['sources'])}
    finally:
        if temporary.exists(): temporary.unlink()
