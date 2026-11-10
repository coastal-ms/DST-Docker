"""Exercise real official package copies in an isolated qualification volume."""
import hashlib
import json
import os
from pathlib import Path
import shutil
from asset_activation import change_package
from asset_version import installed_version

root=Path('/fixture');source=Path('/source')
stage=os.environ['DST_QUALIFICATION_STAGE']
if not __import__('re').fullmatch(r'[a-f0-9]{32}',stage):raise ValueError('Invalid qualification stage.')
if list(root.iterdir()):raise ValueError('Qualification storage must be empty.')
candidate=source/'staged'/stage
build=installed_version(candidate/'server/steamapps/appmanifest_4754530.acf')['installedBuild']
original=(source/'install-state.json').read_bytes()
required=sum(p.stat().st_size for tree in (source/'server',candidate/'server') for p in tree.rglob('*') if p.is_file() and not p.is_symlink())
if shutil.disk_usage(root).free<required+1024**3:raise ValueError('Not enough free qualification storage.')
shutil.copytree(source/'server',root/'server',symlinks=True)
shutil.copytree(candidate/'server',root/'staged'/stage/'server',symlinks=True)
(root/'install-state.json').write_bytes(original)
shutil.copy2(candidate/'install-state.json',root/'staged'/stage/'install-state.json')
activated=change_package(root,stage,build)
assert activated['phase']=='active'
assert installed_version(root/'server/steamapps/appmanifest_4754530.acf')['installedBuild']==build
rolled_back=change_package(root,stage,build,'rollback')
assert rolled_back['phase']=='rolled-back'
assert (root/'install-state.json').read_bytes()==original
assert (root/'staged'/stage/'server').is_dir()
assert (source/'install-state.json').read_bytes()==original
print(json.dumps({'realOfficialPackageCopies':True,'activated':True,'rolledBack':True,'exactOldMetadataRestored':True,
                  'sourceReadOnly':True,'uid':os.getuid(),'build':build,'activeManifestSha256':hashlib.sha256((root/'server/steamapps/appmanifest_4754530.acf').read_bytes()).hexdigest()}))
