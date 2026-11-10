"""Journaled package-directory activation. Game/database coordination is external."""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
import fcntl
import stat
from assets import package_inventory
from asset_version import installed_version
from world_template import read_template


def sync_directory(path):
    descriptor=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def atomic_bytes(path,data):
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as output:
            output.write(data);output.flush();os.fsync(output.fileno())
        temporary.replace(path);sync_directory(path.parent)
    finally:
        if temporary.exists():temporary.unlink()


def read_bytes(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>4*1024*1024:
        raise ValueError('Package activation metadata is missing or invalid.')
    return path.read_bytes()


def digest(data):return hashlib.sha256(data).hexdigest()


def package_fingerprint(server):
    if server.is_symlink() or not server.is_dir():raise ValueError('Package directory is invalid.')
    inventory=package_inventory(server)
    paths=['steamapps/appmanifest_4754530.acf','scripts/setup/templates/world-template.yaml']
    paths+=['scripts/setup/config/'+name for name in ('UserGame.ini','UserEngine.ini','UserServerCustomSettings.ini')]
    paths+=['images/'+entry['archive'] for entry in inventory]
    hashes={}
    for name in paths:
        path=server/name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(server.resolve()):
            raise ValueError('A required package file is missing or outside its package.')
        value=hashlib.sha256()
        with path.open('rb') as source:
            while chunk:=source.read(1024*1024):value.update(chunk)
        hashes[name]=value.hexdigest()
    template=read_template(server/'scripts/setup/templates/world-template.yaml')
    return {'build':installed_version(server/'steamapps/appmanifest_4754530.acf')['installedBuild'],'template':template['sha256'],'files':hashes}


def change_package(root,stage_id,expected_build,mode='activate',checkpoint=lambda phase:None):
    root=Path(root)
    if root.is_symlink() or not root.is_dir() or not re.fullmatch(r'[a-f0-9]{32}',stage_id) or not re.fullmatch(r'[0-9]{1,18}',expected_build):
        raise ValueError('Invalid package activation identity or storage.')
    lock=os.open(root/'.dst-package-activation.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1:
            raise ValueError('Package activation lock is invalid.')
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another package activation or rollback is in progress.') from None
        return _change_package(root,stage_id,expected_build,mode,checkpoint)
    finally:os.close(lock)


def _change_package(root,stage_id,expected_build,mode,checkpoint):
    root=Path(root)
    if not re.fullmatch(r'[a-f0-9]{32}',stage_id) or not re.fullmatch(r'[0-9]{1,18}',expected_build) or mode not in {'activate','rollback'}:
        raise ValueError('Invalid package activation identity.')
    stage=root/'staged'/stage_id;previous=root/'previous'/stage_id
    for path in (root,root/'staged',stage):
        if path.is_symlink() or not path.is_dir():raise ValueError('Package activation storage is invalid.')
    for path in (root/'previous',previous):
        if path.is_symlink():raise ValueError('Package recovery storage is invalid.')
        path.mkdir(exist_ok=True);sync_directory(path.parent)
    journal_path=stage/'activation-state.json'
    if journal_path.is_symlink():raise ValueError('Package activation journal is invalid.')
    active=root/'server';candidate=stage/'server';retired=previous/'server'
    old_state_path=stage/'previous-install-state.json';new_state_path=stage/'candidate-install-state.json'
    def write_journal(phase):
        journal['phase']=phase
        atomic_bytes(journal_path,json.dumps(journal,sort_keys=True).encode())
    if not journal_path.exists():
        if mode!='activate':raise ValueError('There is no package activation to roll back.')
        if retired.exists():raise ValueError('Recovery storage is already occupied.')
        old_state=read_bytes(root/'install-state.json');new_state=read_bytes(stage/'install-state.json')
        report=json.loads(new_state)
        old_package=package_fingerprint(active);new_package=package_fingerprint(candidate)
        if report.get('state')!='downloaded' or new_package['build']!=expected_build or report.get('images')!=package_inventory(candidate):
            raise ValueError('The candidate package did not pass activation validation.')
        journal={'version':1,'stage':stage_id,'expectedBuild':expected_build,'oldPackage':old_package,'newPackage':new_package,
                 'oldStateSha':digest(old_state),'newStateSha':digest(new_state)}
        atomic_bytes(old_state_path,old_state);atomic_bytes(new_state_path,new_state)
        write_journal('prepared')
    else:
        journal=json.loads(read_bytes(journal_path))
        if type(journal.get('version')) is not int or journal.get('version')!=1 or journal.get('stage')!=stage_id or journal.get('expectedBuild')!=expected_build:
            raise ValueError('Package activation journal identity changed.')
        old_state=read_bytes(old_state_path);new_state=read_bytes(new_state_path)
        if digest(old_state)!=journal.get('oldStateSha') or digest(new_state)!=journal.get('newStateSha'):
            raise ValueError('Package activation recovery metadata changed.')
        if journal.get('phase')=='rolled-back' and mode=='activate':
            raise ValueError('This package activation was rolled back. Prepare a new stage before retrying.')
        rollback_phases={'returning-candidate','candidate-returned','restoring-original','original-restored','restoring-metadata','rolled-back'}
        if mode=='activate' and journal.get('phase') in rollback_phases:
            raise ValueError('Finish the package rollback before preparing another activation.')
        if journal.get('phase') not in rollback_phases|{'prepared','retiring','retired','installing','installed','metadata','active'}:
            raise ValueError('Package activation journal phase is invalid.')
    # Inspect directory identities after a crash, including the interval
    # between an atomic rename and the following journal update.
    present=(active.exists(),candidate.exists(),retired.exists())
    if present==(True,True,False):
        layout='original';old_server=active;new_server=candidate
    elif present==(False,True,True):
        layout='retired';old_server=retired;new_server=candidate
    elif present==(True,False,True):
        layout='installed';old_server=retired;new_server=active
    else:raise ValueError('Package directories need review; no activation or rollback was performed.')
    if package_fingerprint(old_server)!=journal['oldPackage'] or package_fingerprint(new_server)!=journal['newPackage']:
        raise ValueError('Package contents changed after activation was prepared.')
    current=read_bytes(root/'install-state.json')
    if digest(current) not in {journal['oldStateSha'],journal['newStateSha']}:
        raise ValueError('The active installer metadata changed. Review it before activation or rollback.')
    def move(source,destination):
        source.rename(destination);sync_directory(source.parent);sync_directory(destination.parent)
    if mode=='activate':
        if layout=='original':
            write_journal('retiring');move(active,retired);checkpoint('after-retire');write_journal('retired');layout='retired'
        if layout=='retired':
            write_journal('installing');move(candidate,active);checkpoint('after-install');write_journal('installed')
        write_journal('metadata');atomic_bytes(root/'install-state.json',new_state);checkpoint('after-metadata');write_journal('active')
        return {'phase':'active','build':journal['newPackage']['build'],'previousBuild':journal['oldPackage']['build']}
    if layout=='installed':
        write_journal('returning-candidate');move(active,candidate);checkpoint('after-return');write_journal('candidate-returned');layout='retired'
    if layout=='retired':
        write_journal('restoring-original');move(retired,active);checkpoint('after-restore');write_journal('original-restored')
    write_journal('restoring-metadata');atomic_bytes(root/'install-state.json',old_state);checkpoint('after-old-metadata');write_journal('rolled-back')
    return {'phase':'rolled-back','build':journal['oldPackage']['build']}


if __name__=='__main__':
    result=change_package('/srv/dst',os.environ.get('DST_PACKAGE_STAGE',''),os.environ.get('DST_PACKAGE_BUILD',''),os.environ.get('DST_PACKAGE_MODE',''))
    print(json.dumps(result))
