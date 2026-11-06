"""Run the bundled Atlas viewer on Linux with the native read-only SQL adapter."""
import hashlib
import fcntl
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import time

APP=Path('/opt/dst/app')
DATA=Path('/data/state/DuneServer/atlas')


class LinuxHost:
    def __init__(self,pid,started):self.pid=pid;self.started=started
    def wait_for_exit(self,stop):
        while not stop.wait(.5):
            try:
                if Path(f'/proc/{self.pid}/stat').read_text().rsplit(')',1)[1].split()[19]!=self.started:return True
            except OSError:return True
        return False
    def close(self):pass


def runtime_root():
    source=APP/'tools/DuneAtlas';manifest=(source/'manifest.json').read_bytes()
    identity=hashlib.sha256(manifest+Path(__file__).read_bytes()).hexdigest()[:16]
    return DATA/'runtimes'/identity


def prepare(root):
    source=APP/'tools/DuneAtlas';root.mkdir(parents=True,exist_ok=True)
    definition=json.loads((source/'manifest.json').read_bytes())
    for relative,digest in definition['files'].items():
        path=Path(relative)
        if path.is_absolute() or '..' in path.parts:raise ValueError('Invalid Atlas package path.')
        original=source/path
        if hashlib.sha256(original.read_bytes()).hexdigest()!=digest:raise ValueError('Atlas package verification failed.')
        target=root/path;target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():shutil.copyfile(original,target)
    for original,target in definition['bootstrapContexts'].items():
        if not (root/target).exists():shutil.copyfile(root/original,root/target)
    query='''param([Parameter(Mandatory)][string]$SqlFile,[Parameter(Mandatory)][string]$OutputFile,[int]$MaxRows=2000)
$ErrorActionPreference='Stop'
$script:AppDir='/opt/dst/app'
. /opt/dst/app/server/lib/DockerDatabase.ps1
. /opt/dst/app/server/lib/Database.ps1
$context=Get-DuneDbContext
if(-not $context.ok){throw $context.message}
$result=Invoke-DuneSqlQuery -Ip docker -Sql ([IO.File]::ReadAllText($SqlFile)) -ReadOnly $true -MaxRows $MaxRows -TimeoutSec 25
$result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OutputFile -Encoding utf8
if(-not $result.ok){throw $result.error}
'''
    for folder in [root,root/'hagga']:
        (folder/'query.ps1').write_text(query)
        (folder/'remote.ps1').write_text('''param([Parameter(Mandatory)][string]$CommandFile,[Parameter(Mandatory)][string]$OutputFile,[int]$Timeout=25,[string]$InputFile)
$ErrorActionPreference='Stop'
$request=@{commandFile=$CommandFile;outputFile=$OutputFile;timeout=$Timeout;inputFile=$InputFile} | ConvertTo-Json -Compress
$request | & python3 /opt/dst/packaging/docker/map-observer-client.py
if($LASTEXITCODE -ne 0){throw 'Native Docker map observation failed.'}
''')


def serve(root):
    sys.path.insert(0,str(root))
    import atlas_lifecycle
    atlas_lifecycle.from_environment=lambda:LinuxHost(os.environ['DST_ATLAS_HOST_PID'],os.environ['DST_ATLAS_HOST_START'])
    os.environ.update(DST_ATLAS_APP_ROOT=str(APP),DST_ATLAS_SNAPSHOT_ROOT=str(DATA/'snapshots'),
        DST_ATLAS_PREFERENCES_ROOT=str(DATA/'settings'),DST_ATLAS_ASSET_ROOT=str(DATA/'assets/icons'),
        DST_ATLAS_PROFILE_ROOT=str(DATA/'profiles'),DST_ATLAS_PORT='0')
    runpy.run_path(str(root/'server.py'),run_name='__main__')


def session(pid):
    DATA.mkdir(parents=True,exist_ok=True)
    with (DATA/'startup.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return locked_session(pid)


def locked_session(pid):
    root=runtime_root();ready=root/'ready.json'
    def existing():
        try:
            record=json.loads(ready.read_text());process=int(record['pid'])
            command=Path(f'/proc/{process}/cmdline').read_bytes().split(b'\0')
            if os.fsencode(__file__) in command and os.fsencode(str(root)) in command:return record
        except (OSError,ValueError,KeyError):pass
        return None
    record=existing()
    if record:return record
    prepare(root)
    env={**os.environ,'DST_ATLAS_HOST_PID':str(pid),'DST_ATLAS_HOST_START':Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]}
    ready.unlink(missing_ok=True)
    with (DATA/'host.log').open('ab') as log:
        process=subprocess.Popen([sys.executable,__file__,'serve',str(root)],cwd=root,env=env,stdout=log,stderr=log,start_new_session=True)
    deadline=time.monotonic()+7
    while time.monotonic()<deadline:
        record=existing()
        if record:return record
        if process.poll() is not None:raise RuntimeError('Atlas host failed to start.')
        time.sleep(.1)
    return None


if __name__=='__main__':
    if sys.argv[1]=='serve':serve(Path(sys.argv[2]))
    else:print(json.dumps(session(int(sys.argv[1]))))
