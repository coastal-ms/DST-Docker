"""Apply a persisted warm floor to the owned director's live override."""
import json
import re
import sys
import time
import urllib.error
import urllib.request


def apply(request):
    host=request.get('host');name=request.get('map');floor=request.get('floor')
    if not isinstance(host,str) or not re.fullmatch(r'dst-[a-f0-9]{32}-director',host):raise ValueError('Invalid director identity.')
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_]{1,80}',name):raise ValueError('Invalid map identity.')
    if type(floor) is not int or not 0<=floor<=64:raise ValueError('Invalid map floor.')
    base='http://'+host+':11717/'
    def read():
        with urllib.request.urlopen(base+'v0/battlegroup',timeout=10) as response:
            raw=response.read(8*1024*1024+1)
        if len(raw)>8*1024*1024:raise ValueError('Director response exceeds its limit.')
        return json.loads(raw)['instancedMaps'][name]
    # A newly started director can be running before its HTTP API is ready.
    # Keep this map operation pending while that owned service finishes booting.
    deadline=time.monotonic()+30
    while True:
        try:
            current=read()
            break
        except (urllib.error.URLError,TimeoutError,ConnectionError) as error:
            if isinstance(error,urllib.error.HTTPError) and error.code not in {408,502,503,504}:raise
            if time.monotonic()>=deadline:raise ValueError('The director is still starting; retry the map control.') from None
            time.sleep(.25)
    pending=current.get('webOverrideCfg') or {}
    pending_floor=next((value for key,value in pending.items() if key.lower()=='minservers'),floor)
    if current['cfg']['minServers']==floor and pending_floor==floor:return {'applied':True}
    override={key:value for key,value in (current.get('webOverrideCfg') or {}).items() if key.lower()!='minservers'}
    override['MinServers']=floor
    payload=json.dumps({'MapName':name,'ClassicalInstancingGroupConfig':override}).encode()
    call=urllib.request.Request(base+'v0/BattlegroupUpdateServerGroupConfig',data=payload,method='POST',headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(call,timeout=10) as response:response.read(65536)
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        if read()['cfg']['minServers']==floor:return {'applied':True}
        time.sleep(.25)
    raise ValueError('Director has not applied the saved warm setting yet.')


if __name__=='__main__':
    try:print(json.dumps(apply(json.loads(sys.argv[1]))))
    except Exception:
        print('The saved warm setting could not be activated in the live director.',file=sys.stderr)
        sys.exit(1)
