"""Observe only the bound world's loopback Director UI endpoint."""


def endpoint(state, engine):
    entry=state.get('services',{}).get('director')
    if not entry:return {'available':False}
    observed=engine.assert_owned(entry['id'],state['id'],'director')
    port=(state.get('worldPlan') or {}).get('ports',{}).get('director')
    if type(port) is not int or not 1024<=port<=65535:
        raise ValueError('The Director endpoint has no valid owned port.')
    bindings=observed.get('HostConfig',{}).get('PortBindings',{}).get('11717/tcp')
    if bindings != [{'HostIp':'127.0.0.1','HostPort':str(port)}]:
        raise ValueError('The Director endpoint is not the owned loopback binding.')
    return {'available':observed['State']['Status']=='running','port':port}
