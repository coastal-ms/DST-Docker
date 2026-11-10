"""Fixed, unprivileged INI helper using only this world's existing Saved storage."""
import os
from pathlib import Path
import re
from urllib.parse import quote


def create(state,engine,control):
    project=state['id']
    if not re.fullmatch(r'[a-f0-9]{32}',project):raise ValueError('Invalid settings world.')
    control_labels=engine.request('GET','/volumes/'+quote(control,safe='')).get('Labels') or {}
    if control_labels.get('com.docker.compose.volume')!='dst-map-control':
        raise ValueError('The settings control volume is not owned by this installation.')
    game=state.get('services',{}).get('game-1',{})
    if game.get('phase')!='prepared':raise ValueError('Prepare Hagga Basin saved files before editing settings.')
    observed=engine.assert_owned(game['id'],project,'game-1')
    volume='dst-'+project+'-game-1-saved'
    mounts=[m for m in observed.get('Mounts',[]) if m.get('Destination')=='/home/dune/server/DuneSandbox/Saved']
    if len(mounts)!=1 or mounts[0].get('Type')!='volume' or mounts[0].get('Name')!=volume:
        raise ValueError('The authoritative settings storage does not belong to this world.')
    labels=engine.request('GET','/volumes/'+quote(volume,safe='')).get('Labels') or {}
    if labels.get('io.dst.managed')!='true' or labels.get('io.dst.project')!=project:
        raise ValueError('The settings Saved volume is not owned.')
    directory=Path('/map-control/settings')
    if directory.is_symlink():raise ValueError('The settings control directory is unsupported.')
    directory.mkdir(mode=0o770,exist_ok=True)
    os.chown(directory,-1,10001);directory.chmod(0o770)
    image=engine.inspect(os.environ['HOSTNAME'])['Image']
    spec={'Image':image,'User':'1000:10001',
          'Entrypoint':['python3','-B','/opt/dst-manager/settings_service.py'],
          'Labels':{'io.dst.managed':'true','io.dst.project':project,'io.dst.component':'settings'},
          'HostConfig':{'NetworkMode':'none','Init':True,'ReadonlyRootfs':True,'CapDrop':['ALL'],
                        'SecurityOpt':['no-new-privileges:true'],'Memory':64*1024**2,'MemorySwap':64*1024**2,
                        'PidsLimit':32,'RestartPolicy':{'Name':'unless-stopped'},
                        'Mounts':[{'Type':'volume','Source':volume,'Target':'/saved'},
                                  {'Type':'volume','Source':control,'Target':'/control'}],
                        'LogConfig':{'Type':'json-file','Config':{'max-size':'2m','max-file':'2'}}}}
    return engine.request('POST','/containers/create?name=dst-'+project+'-settings',spec)['Id']
