"""Generate verified compatibility files from the owner's immutable game image.

This utility has no Docker socket, network or Saved mount. It never executes the
game and cannot activate its output. Only a completed, verified report is usable
by the management controller.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

BUILDS = frozenset({'2147284', '2156652', '2160922', '2162777', '2168446', '2173753', '2177228', '2180427', '2181988'})
STEMS = {
    'modules': 'DuneSandbox/Content/Dune/Systems/Vehicles/Modules/DT_Tank_Modules',
    'blueprint': 'DuneSandbox/Content/Dune/Systems/Vehicles/Blueprints/GroundVehicles/BP_Tank_CHOAM',
}
OVERLAY = 'pakchunk999-DSTRegisTank-2147284-LinuxServer_P'
OVERLAY_HASHES = {
    'pak': '75e7144577253917f6da7312ef5e585b12fb728226a22b0938323751a6b555cd',
    'ucas': '13011a68170df5a9320782691768b0b0bd568610bc682ec1979e979de534c01e',
    'utoc': '12781c923dcace79204bfecaf0ff4ea49c41ec6a07e68fe81fd3feb96767ced5',
}
HASH = re.compile(r'[a-f0-9]{64}')


def digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('A required compatibility file is missing or is a symbolic link.')
    result = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def validate_recipe(recipe, build):
    if build not in BUILDS or type(recipe.get('schema')) is not int or recipe.get('schema') != 1 or recipe.get('build') != build:
        raise ValueError('The installed server build has no accepted Tank recipe.')
    for name in ('cleanExecutableSha256', 'patchedExecutableSha256'):
        if not isinstance(recipe.get(name), str) or not HASH.fullmatch(recipe[name]):
            raise ValueError('The Tank executable recipe is invalid.')
    expected = {stem + '.' + extension for stem in STEMS.values() for extension in ('uasset', 'uexp')}
    stock = recipe.get('stockFiles')
    if not isinstance(stock, dict) or set(stock) != expected or any(not isinstance(value, str) or not HASH.fullmatch(value) for value in stock.values()):
        raise ValueError('The Tank asset recipe is invalid.')
    sites = recipe.get('sites')
    if not isinstance(sites, list) or not 1 <= len(sites) <= 128:
        raise ValueError('The Tank patch recipe is invalid.')
    ranges = []
    for site in sites:
        if not isinstance(site, list) or len(site) != 3:
            raise ValueError('A Tank patch site is invalid.')
        offset, before, after = site
        if (type(offset) is not int or offset < 0 or not isinstance(before, str) or not isinstance(after, str)
                or not re.fullmatch(r'(?:[a-f0-9]{2}){1,32768}', before)
                or not re.fullmatch(r'(?:[a-f0-9]{2}){1,32768}', after) or len(before) != len(after)):
            raise ValueError('A Tank patch site is invalid.')
        ranges.append((offset, offset + len(before) // 2))
    ranges.sort()
    if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
        raise ValueError('Tank patch sites overlap.')


def patch_binary(source, output, recipe):
    if digest(source) != recipe['cleanExecutableSha256']:
        raise ValueError('The installed executable does not match the accepted Tank recipe.')
    with source.open('rb') as original, output.open('xb') as generated:
        shutil.copyfileobj(original, generated, 1024 * 1024)
    with output.open('r+b') as generated:
        for offset, before, after in recipe['sites']:
            expected = bytes.fromhex(before)
            generated.seek(offset)
            if generated.read(len(expected)) != expected:
                raise ValueError('A Tank compatibility patch site does not match.')
            generated.seek(offset)
            generated.write(bytes.fromhex(after))
        generated.flush()
        os.fsync(generated.fileno())
    if digest(output) != recipe['patchedExecutableSha256']:
        raise ValueError('The generated Tank executable did not pass verification.')
    if digest(source) != recipe['cleanExecutableSha256']:
        raise ValueError('The source game executable changed during preparation.')
    output.chmod(0o755)


def run(arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=180, check=False)
    if result.returncode:
        raise ValueError('A Tank asset tool failed: ' + (result.stderr or result.stdout).strip()[:400])


def generate(build, work=Path('/work'), server=Path('/home/dune/server'), tools=Path('/tools')):
    if build not in BUILDS:
        raise ValueError('The installed server build has no accepted Tank recipe.')
    recipe = json.loads((tools / 'recipes' / (build + '.json')).read_text())
    validate_recipe(recipe, build)
    # Reject an unknown binary before creating output. Never reuse an earlier
    # partial directory or let a stale success report authorize activation.
    binary = server / 'DuneSandbox/Binaries/Linux/DuneSandboxServer-Linux-Shipping'
    if digest(binary) != recipe['cleanExecutableSha256']:
        raise ValueError('The installed executable does not match the accepted Tank recipe.')
    if (work / 'report.json').exists() or (work / 'report.json').is_symlink():
        raise ValueError('Use a new Tank preparation directory.')
    output = work / 'output'
    output.mkdir(mode=0o750)
    patch_binary(binary, output / 'DuneSandboxServer-Linux-Shipping', recipe)
    paks = server / 'DuneSandbox/Content/Paks'
    for name in ('DT_Tank_Modules', 'BP_Tank_CHOAM'):
        run([str(tools / 'native/retoc'), 'to-legacy', str(paks), str(work / 'stock'), '--filter', name, '--no-shaders', '--no-parallel'])
    for relative, expected in recipe['stockFiles'].items():
        if digest(work / 'stock' / relative) != expected:
            raise ValueError('The installed Tank assets do not match the accepted recipe.')
    for kind, stem in STEMS.items():
        generated = work / 'generated' / (stem + '.uasset')
        generated.parent.mkdir(parents=True, exist_ok=True)
        stock_json, changed_json = work / (kind + '-stock.json'), work / (kind + '-generated.json')
        run([str(tools / 'codec/DuneRegisAssetCodec'), 'tojson', str(work / 'stock' / (stem + '.uasset')), str(stock_json)])
        run([str(tools / 'generator/DuneRegisTanks'), kind, str(stock_json), str(changed_json)])
        run([str(tools / 'codec/DuneRegisAssetCodec'), 'fromjson', str(changed_json), str(generated)])
    run([str(tools / 'native/retoc'), 'to-zen', str(work / 'generated'), str(output / (OVERLAY + '.utoc')), '--version', 'UE5_2', '--no-parallel'])
    files = {'DuneSandboxServer-Linux-Shipping': recipe['patchedExecutableSha256']}
    files.update({OVERLAY + '.' + extension: expected for extension, expected in OVERLAY_HASHES.items()})
    for name, expected in files.items():
        if digest(output / name) != expected:
            raise ValueError('A generated Tank compatibility file did not pass verification.')
    report = {'ok': True, 'build': build, 'files': {name: {'sha256': expected, 'bytes': (output / name).stat().st_size} for name, expected in files.items()}}
    temporary = work / 'report.pending'
    with temporary.open('x') as destination:
        json.dump(report, destination)
        destination.flush()
        os.fsync(destination.fileno())
    temporary.replace(work / 'report.json')
    return report


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('Supply the installed server build.')
        print(json.dumps(generate(sys.argv[1])))
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}), file=sys.stderr)
        raise SystemExit(1)
