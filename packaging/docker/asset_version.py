"""Read only public version fields from the fixed official Steam manifest."""
from pathlib import Path
import re

APP_ID = '4754530'
MANIFEST = Path('/assets/server/steamapps/appmanifest_4754530.acf')


def installed_version(manifest=MANIFEST):
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError('The official installed Steam manifest is unavailable.')
    with manifest.open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('The official installed Steam manifest is too large.')
    text = raw.decode('utf-8-sig')
    fields = {}
    for name in ('appid', 'buildid'):
        values = re.findall(r'^\s*"' + name + r'"\s*"([0-9]{1,18})"\s*$', text, re.M)
        if len(values) != 1:
            raise ValueError('The official installed Steam manifest has invalid version fields.')
        fields[name] = values[0]
    if fields['appid'] != APP_ID or int(fields['buildid']) <= 0:
        raise ValueError('The installed Steam manifest does not identify the official self-host package.')
    return {'appId': APP_ID, 'installedBuild': fields['buildid']}
