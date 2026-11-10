"""Publish a sanitized, read-only Docker snapshot. Never accepts commands."""
import http.client
import json
import os
import re
import socket
import time
from pathlib import Path


class DockerConnection(http.client.HTTPConnection):
    def __init__(self):
        super().__init__('localhost', timeout=5)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/var/run/docker.sock')


def get(path):
    connection = DockerConnection()
    try:
        connection.request('GET', path)
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(f'Docker read failed ({response.status})')
        return json.loads(response.read(4 * 1024 * 1024))
    finally:
        connection.close()


def memory_values(stats):
    memory = stats.get('memory_stats', {})
    counters = memory.get('stats', {})
    cache = counters.get('inactive_file', counters.get('total_inactive_file', 0))
    usage = max(0, int(memory.get('usage', 0)))
    return {'usedBytes': max(0, usage - min(usage, int(cache))),
            'limitBytes': max(0, int(memory.get('limit', 0))),
            'swapUsedBytes': counters.get('swap',counters.get('total_swap')),
            'rawBytes': usage}


def collect(read=get):
    info = read('/info')
    project = os.environ.get('DST_OBSERVE_PROJECT', '')
    containers = []
    for container in read('/containers/json?all=true'):
        labels = container.get('Labels') or {}
        name=(container.get('Names') or ['unnamed'])[0].lstrip('/')
        if labels.get('io.dst.managed')=='true' and re.fullmatch(r'dst-[a-f0-9]{32}-(?:game-[1-9][0-9]*|director|text-router|gateway|rmq-admin|rmq-game)-previous-[a-f0-9]{8}',name):
            continue
        if project and labels.get('com.docker.compose.project') != project:
            continue
        image = container.get('Image', '')
        if not image.startswith('registry.funcom.com/funcom/self-hosting/'):
            continue
        item = {'name': name,
                'image': image, 'state': container.get('State', 'unknown'),
                'status': container.get('Status', ''), 'memory': None}
        if labels.get('io.dst.managed')=='true' and re.fullmatch(r'[a-f0-9]{32}',labels.get('io.dst.project','')):
            item['managed']=True
            component=labels.get('io.dst.component','')
            if re.fullmatch(r'[a-z0-9-]{1,64}',component):item['component']=component
            map_name=labels.get('io.dst.map','')
            if re.fullmatch(r'[A-Za-z0-9_]{1,100}',map_name):item['map']=map_name
        if item['state'] == 'running':
            try:
                item['memory'] = memory_values(read('/containers/' + container['Id'] + '/stats?stream=false&one-shot=true'))
            except (OSError, RuntimeError, ValueError):
                item['sampleUnavailable'] = True
        containers.append(item)
    return {'available': True, 'observedAt': time.time(), 'readOnly': True,
            'host': {'memoryBytes': info.get('MemTotal', 0), 'cpus': info.get('NCPU', 0),
                     'engineVersion': info.get('ServerVersion', '')},
            'containers': sorted(containers, key=lambda row: row['name'])}


def publish(snapshot, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(snapshot), encoding='utf-8')
    temporary.chmod(0o644)
    temporary.replace(output)


if __name__ == '__main__':
    output = Path('/observations/status.json')
    while True:
        try:
            publish(collect(), output)
        except (OSError, RuntimeError, ValueError, http.client.HTTPException):
            publish({'available': False, 'observedAt': time.time(), 'readOnly': True,
                     'error': 'Docker observations are unavailable. Check the observer service.'}, output)
        time.sleep(10)
