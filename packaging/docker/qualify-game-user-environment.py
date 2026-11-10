"""Execute the real wrapper in the official image with an inert probe binary."""
import json,os,re,struct,time,uuid
from pathlib import Path
from engine import Engine,EngineConnection
from assets import package_inventory
project=os.environ['DST_QUALIFY_PROJECT'];assert re.fullmatch(r'[a-f0-9]{32}',project)
engine=Engine();network='dst-'+project+'-network';volume='dst-'+project+'-game-1-saved'
existing=engine.request('GET','/networks/'+network,expected=(200,404))
if existing:assert existing['Labels']['io.dst.project']==project and not existing['Containers']
else:engine.request('POST','/networks/create',{'Name':network,'Labels':{'io.dst.managed':'true','io.dst.project':project}})
image=next(tag for entry in package_inventory(Path('/assets/server')) if entry['archive']=='battlegroup/server.tar' for tag in entry['tags'])
engine.ensure_package_image('/assets/server/images/battlegroup/server.tar',image)
identifier=engine.create_component(project,'game-1',image,network,environment={'HOME':'/root'},entrypoint=['/dst-game.sh'],command=[],memory=256*1024**2,map_name='Survival_1',
    volumes=[{'name':volume,'target':'/home/dune/server/DuneSandbox/Saved','mustBeNew':True}])
probe='''#!/bin/sh
set -eu
[ "$(id -u)" = 1000 ]
[ "$HOME" = /home/dune ]
[ "$USER" = dune ]
[ "$LOGNAME" = dune ]
[ "$XDG_CONFIG_HOME" = /home/dune/.config ]
ini="$HOME/.config/Epic/Unreal Engine/Engine/Config/UserGame.ini"
[ -r "$ini" ]
slots=$(awk -F= '/^PlayerInventoryStartingSize=/{print $2}' "$ini")
[ "$slots" = 125 ]
printf '{"uid":1000,"home":"/home/dune","userIniSlots":125,"rootEnvironmentReplaced":true}\n'
'''
engine.upload_component_files(identifier,project,'game-1',{
    'dst-game.sh':{'data':Path('/native-game.sh').read_text(),'mode':0o555},
    'home/dune/server/DuneSandbox/Binaries/Linux/DuneSandboxServer-Linux-Shipping':{'data':probe,'mode':0o555},
    'home/dune/server/DuneSandbox/Saved/UserSettings/UserGame.ini':{'data':'[/Script/DuneSandbox.InventorySystemSettings]\nPlayerInventoryStartingSize=125\n','uid':1000,'gid':65534,'mode':0o600}})
engine.lifecycle(identifier,project,'start');deadline=time.monotonic()+90
while True:
    observed=engine.assert_owned(identifier,project,'game-1')
    if observed['State']['Status']=='exited':break
    if time.monotonic()>deadline:raise RuntimeError('The existing environment probe remains active; inspect its project identity.')
    time.sleep(.2)
assert observed['State']['ExitCode']==0,'The real wrapper failed its user-environment probe.'
c=EngineConnection()
try:c.request('GET','/containers/'+identifier+'/logs?stdout=1&stderr=0');r=c.getresponse();raw=r.read(65536)
finally:c.close()
chunks=[];offset=0
while offset+8<=len(raw):
    length=struct.unpack('>I',raw[offset+4:offset+8])[0];offset+=8;chunks.append(raw[offset:offset+length]);offset+=length
proof=json.loads(b''.join(chunks))
engine.request('DELETE','/containers/'+identifier,expected=(204,))
assert engine.request('GET','/volumes/'+volume)['Labels']['io.dst.project']==project
engine.request('DELETE','/volumes/'+volume,expected=(204,))
assert engine.request('GET','/networks/'+network)['Labels']['io.dst.project']==project
engine.request('DELETE','/networks/'+network,expected=(204,))
print(json.dumps({**proof,'actualOfficialImage':True,'realWrapperExecuted':True,'noGameOrWorldStarted':True,'fixtureResourcesRemoved':True}))
