"""Inventory baseline routes and their native-host dependencies for parity review."""
import json
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
baseline = '9961785c7fad4ed7de63ae726addd5fde0288983'
routes = []
for path in sorted((root / 'app/server/routes').glob('*.ps1')):
    source = subprocess.check_output(['git', '-C', str(root), 'show', f'{baseline}:app/server/routes/{path.name}'], text=True, encoding='utf-8')
    for match in re.finditer(r"Register-DuneRoute\s+-Method\s+(\w+)\s+-Path\s+'([^']+)'", source):
        routes.append({'source': path.name, 'method': match[1], 'path': match[2],
                       'dockerStatus': 'not-yet-verified', 'featureDisposition': 'preserve'})
    for match in re.finditer(r"Register-DuneWebSocket\s+-Path\s+'([^']+)'", source):
        routes.append({'source': path.name, 'method': 'CONNECT', 'path': match[1],
                       'dockerStatus': 'not-yet-verified', 'featureDisposition': 'preserve'})
for route in routes:
    if route['source'].startswith('Solo') or route['path'].startswith('/api/solo'):
        route.update(dockerStatus='out-of-scope',featureDisposition='standalone-windows-only')
report = {'baseline': baseline, 'routeCount': len(routes), 'routes': routes,
          'requirements': ['Preserve existing features, permissions, confirmations, backup/offline/write safeguards and result semantics.',
                           'Replace Windows packaged helpers with Linux-native equivalents.',
                           'Replace Hyper-V/Kubernetes transports with Docker adapters.',
                           'Solo stays in the standalone Windows DST application; Docker hosts servers on native Linux and WSL without a Windows companion.',
                           'Adapt map collectors and browser presentation without losing map features.',
                           'VM-data migration is lower priority; no public publication authorized.']}
if len(sys.argv) != 2: raise SystemExit('Usage: parity-inventory.py OUTPUT.json')
Path(sys.argv[1]).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(f'Inventoried {len(routes)} baseline routes; none assumed ported merely because the UI renders.')
