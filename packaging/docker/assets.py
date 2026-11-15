"""Acquire the official Linux self-host package in DST's own storage."""
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time
import urllib.request
import re
from asset_version import installed_version

ROOT = Path('/srv/dst')
STEAM_URL = 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz'
APP_ID = '4754530'
MISSING_CONFIGURATION = "Steam did not provide the server package configuration after three attempts. Retry Update Server."
MANIFEST_RECOVERY_FAILED = "Steam still reports server package state 0x6 after three attempts. Automatic app-manifest cleanup and retry did not resolve it. Check free disk space and Steam connectivity, then retry Update Server."
MAX_ATTEMPTS = 3
MANIFEST_RETRY_SECONDS = 20
STATE_0X6 = re.compile(r"\bApp\s+['\"]4754530['\"]\s+state\s+is\s+0x0*6\b", re.IGNORECASE)


def write_state(state, root=ROOT, **fields):
    payload = {'state': state, 'updatedAt': time.time(), **fields}
    temporary = root / 'install-state.tmp'
    temporary.write_text(json.dumps(payload), encoding='utf-8')
    temporary.replace(root / 'install-state.json')


def package_inventory(server):
    expected = ['battlegroup/server.tar', 'battlegroup/server-bg-director.tar',
                'battlegroup/server-gateway.tar', 'battlegroup/server-text-router.tar',
                'battlegroup/server-rabbitmq.tar', 'battlegroup/server-db-utils.tar',
                'prerequisites/igw-postgres.tar']
    missing = [name for name in expected if not (server / 'images' / name).is_file()]
    if missing: raise ValueError('Official package is incomplete: ' + ', '.join(missing))
    manifest = server / 'steamapps/appmanifest_4754530.acf'
    if not manifest.is_file(): raise ValueError('Official Steam application manifest is missing.')
    # Enumerate only the distributed Funcom images, never credentials or saves.
    images = []
    for relative in expected:
        archive = server / 'images' / relative
        with tarfile.open(archive) as package:
            member = package.getmember('manifest.json')
            if member.size > 1024 * 1024: raise ValueError('Image manifest is too large.')
            entries = json.load(package.extractfile(member))
            tags = [tag for entry in entries for tag in entry.get('RepoTags', [])]
            if not tags or any(not tag.startswith('registry.funcom.com/funcom/self-hosting/') for tag in tags):
                raise ValueError('Unexpected image reference in official package.')
        images.append({'archive': relative, 'tags': tags, 'bytes': archive.stat().st_size})
    return images


def reset_app_manifest(root):
    """Remove only this install's manifest, never follow a link out of its tree."""
    server = root / 'server'
    directory = server / 'steamapps'
    manifest = directory / ('appmanifest_' + APP_ID + '.acf')
    if any(path.is_symlink() for path in (server, directory, manifest)) or not manifest.resolve().is_relative_to(root.resolve()):
        raise ValueError('App-manifest cleanup stopped because the download path is not local to this installation.')
    if manifest.exists():
        if not manifest.is_file():
            raise ValueError('App-manifest cleanup stopped because the manifest is not a regular file.')
        manifest.unlink()
        return 'Removed the download app manifest; SteamCMD will regenerate it.'
    return 'The download app manifest is already absent; SteamCMD will regenerate it.'


def retry_message(log, message):
    with log.open('a', encoding='utf-8') as output:
        output.write('[DST] ' + message + '\n')
    print(message, flush=True)


def install(root=ROOT, expected_build=None):
    if expected_build is not None and not re.fullmatch(r'[0-9]{1,18}', expected_build):
        raise ValueError('Invalid expected official package build.')
    root.mkdir(parents=True, exist_ok=True)
    steam = root / 'steam'
    server = root / 'server'
    steam.mkdir(exist_ok=True)
    server.mkdir(exist_ok=True)
    log = root / 'steam-install.log'
    try:
        write_state('preparing', root)
        if not (steam / 'steamcmd.sh').exists():
            archive = root / 'steamcmd_linux.tar.gz'
            with urllib.request.urlopen(STEAM_URL, timeout=30) as response, archive.open('wb') as output:
                while data := response.read(1024 * 1024): output.write(data)
            with tarfile.open(archive, 'r:gz') as package:
                package.extractall(steam, filter='data')
            archive.unlink()
        write_state('downloading', root, appId=APP_ID)
        command = [str(steam / 'steamcmd.sh'), '+@ShutdownOnFailedCommand', '1',
                   '+@NoPromptForPassword', '1', '+@sSteamCmdForcePlatformType', 'linux',
                   '+force_install_dir', str(server), '+login', 'anonymous',
                   '+app_update', APP_ID, 'validate', '+logoff', '+quit']
        for attempt in range(MAX_ATTEMPTS):
            with log.open('w' if attempt == 0 else 'a', encoding='utf-8') as output:
                offset = output.tell()
                result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, env={**os.environ, 'HOME': '/home/dst'}, check=False)
            with log.open(encoding='utf-8', errors='replace') as output:
                output.seek(offset)
                attempt_output = output.read()
            state_0x6 = STATE_0X6.search(attempt_output) is not None
            if state_0x6:
                # Steam's app error takes precedence over a successful launcher
                # exit. A later attempt must be judged from its own output only.
                if attempt == MAX_ATTEMPTS - 1:
                    retry_message(log, MANIFEST_RECOVERY_FAILED)
                    raise RuntimeError(MANIFEST_RECOVERY_FAILED)
                cleanup = reset_app_manifest(root)
                message = (f'SteamCMD reported app {APP_ID} state 0x6. {cleanup} '
                           f'Retrying in {MANIFEST_RETRY_SECONDS} seconds '
                           f'(attempt {attempt + 2} of {MAX_ATTEMPTS}).')
                retry_message(log, message)
                write_state('downloading', root, appId=APP_ID, attempt=attempt + 2,
                            maxAttempts=MAX_ATTEMPTS, retryReason='steam-state-0x6',
                            retryAt=time.time() + MANIFEST_RETRY_SECONDS, message=message)
                time.sleep(MANIFEST_RETRY_SECONDS)
                continue
            if result.returncode == 0:
                break
            missing_configuration = "Failed to install app '4754530' (Missing configuration)" in attempt_output
            if result.returncode != 8 or not missing_configuration:
                raise RuntimeError(f'SteamCMD exited with code {result.returncode}. Inspect the local installation log.')
            if attempt == MAX_ATTEMPTS - 1:
                raise RuntimeError(MISSING_CONFIGURATION)
            time.sleep(2 * (attempt + 1))
        images = package_inventory(server)
        version = installed_version(server / 'steamapps/appmanifest_4754530.acf')
        if expected_build is not None and version['installedBuild'] != expected_build:
            raise ValueError('Steam delivered a different build than the requested update. The running installation was left unchanged.')
        write_state('downloaded', root, appId=APP_ID, installedBuild=version['installedBuild'], images=images)
        print('Official Linux server package downloaded and image inventory verified.', flush=True)
    except Exception as error:
        write_state('failed', root, error=str(error))
        raise


def main():
    stage = os.environ.get('DST_ASSETS_STAGE_ID')
    if stage is None:
        install()
    else:
        expected = os.environ.get('DST_EXPECTED_BUILD', '')
        if not re.fullmatch(r'[a-f0-9]{32}', stage) or not re.fullmatch(r'[0-9]{1,18}', expected):
            raise ValueError('A fixed update identity and expected build are required.')
        # A staged update owns its complete SteamCMD tree. It cannot rewrite
        # the active package, its manifest, installer state or Steam cache.
        install(ROOT / 'staged' / stage, expected_build=expected)


if __name__ == '__main__': main()
