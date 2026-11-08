"""Prepare a persistent, copy-only host backup folder; never changes existing copies."""
import argparse,json,os,re
from pathlib import Path

MARKER='.dst-backup-mirror.json'

def prepare(project,directory,output,distro=''):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}',project):raise ValueError('Choose this installation’s Compose project.')
    selected=Path(directory).expanduser()
    if not selected.is_absolute() or selected.is_symlink():raise ValueError('Choose an absolute, dedicated backup folder.')
    selected=selected.resolve()
    if selected in {Path('/'),Path('/root'),Path('/home'),Path('/tmp')} or any(selected==Path(root) or Path(root) in selected.parents for root in ('/etc','/proc','/sys','/dev','/usr','/bin','/sbin','/run','/var/lib/docker')):
        raise ValueError('Choose a dedicated backup folder outside system directories.')
    target=Path(output).resolve()
    config={'x-dst-backup-mirror-format':1,'x-dst-backup-mirror-folder':str(selected),
            'services':{'manager':{'volumes':[{'type':'bind','source':str(selected),'target':'/mirror'}]}}}
    if target.exists():
        if json.loads(target.read_text())!=config:raise ValueError('A different backup folder is already configured. Preserve it and review the deployment before changing folders.')
        return config
    selected.mkdir(mode=0o700,parents=True,exist_ok=True)
    marker=selected/MARKER
    expected={'format':1,'composeProject':project}
    if marker.exists() or marker.is_symlink():
        if marker.is_symlink():raise ValueError('The backup folder marker needs review.')
        actual=json.loads(marker.read_text())
        if any(actual.get(key)!=value for key,value in expected.items()):raise ValueError('The backup folder belongs to another installation.')
    else:
        if distro and not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',distro):raise ValueError('The WSL distribution name is invalid.')
        fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:json.dump({**expected,'wslDistro':distro},stream)
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x') as stream:json.dump(config,stream,indent=2);stream.write('\n')
    return config

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True);parser.add_argument('--directory',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    try:
        value=prepare(args.project,args.directory,args.output,os.environ.get('WSL_DISTRO_NAME',''))
        print(json.dumps({'folder':value['x-dst-backup-mirror-folder'],'copyingEnabled':False,'existingCopiesPreserved':True}))
    except (ValueError,OSError,json.JSONDecodeError) as error:parser.exit(1,str(error)+'\n')
