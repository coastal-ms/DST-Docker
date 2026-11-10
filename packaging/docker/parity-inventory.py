"""Inventory baseline routes and their native-host dependencies for parity review."""
import argparse
import json
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[2]
baseline = '9961785c7fad4ed7de63ae726addd5fde0288983'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('output',type=Path)
parser.add_argument('--baseline-repository',type=Path,default=root,help='Read-only checkout containing the original baseline commit, if this private repository does not retain it.')
args=parser.parse_args()
repository=args.baseline_repository
if subprocess.run(['git','-C',str(repository),'cat-file','-e',baseline+'^{commit}'],capture_output=True).returncode:
    parser.error('The original baseline is absent. Supply --baseline-repository pointing to a checkout that contains it.')
routes = []
baseline_paths=subprocess.check_output(['git','-C',str(repository),'ls-tree','-r','--name-only',baseline,'--','app/server/routes'],text=True,encoding='utf-8').splitlines()
for relative in sorted(path for path in baseline_paths if path.endswith('.ps1')):
    path=Path(relative)
    source = subprocess.check_output(['git', '-C', str(repository), 'show', f'{baseline}:{relative}'], text=True, encoding='utf-8')
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
args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(f'Inventoried {len(routes)} baseline routes; none assumed ported merely because the UI renders.')
