"""Narrow orchestration protocol used by the installed stock director.

This is a Docker projection, not a general Kubernetes server. Only the
installation's fixed map catalogue and replica/partition fields are writable.
"""
import copy
import re
import configparser


def classic_automatic_maps(source):
    parser=configparser.RawConfigParser(strict=False)
    parser.read_string(source)
    return [name.strip() for name in parser.sections() if parser.getboolean(name,'EnableAutomaticInstanceScaling',fallback=False)]


def resource_name(world,map_name):
    return world+'-'+re.sub('[^a-z0-9-]','-',map_name.lower()).strip('-')


def desired_partitions(state,map_info):
    targets=state.get('mapTargets',{})
    return [partition for index,partition in enumerate(map_info['partitions'])
            if targets.get('game-'+str(partition),'running' if index<map_info['initialReplicas'] else 'stopped')=='running']


def scale_resource(state,map_info):
    world=state['worldId'];partitions=desired_partitions(state,map_info)
    return {'apiVersion':'igw.funcom.com/v1','kind':'ServerSetScale',
            'metadata':{'name':resource_name(world,map_info['map']),'namespace':world,
                        'resourceVersion':str(state.get('scaleRevision',0)),
                        'annotations':{'igw.funcom.com/map-name':map_info['map']}},
            'spec':{'replicas':len(partitions),'partitions':partitions,'additionalArguments':[]}}


def snapshot(state,template,db_password):
    world=state['worldId'];document=copy.deepcopy(template['world'])
    document['metadata'].update(name=world,namespace=world,resourceVersion=str(state.get('scaleRevision',0)))
    database=document['spec']['database']['template']['spec']['deployment']['spec']
    database.update(gameDatabaseName='dune',user='dune',password=db_password)
    # The director requires only the application role; never provide the
    # administrative credential through this private compatibility response.
    database.pop('superPassword',None);database.pop('superUser',None)
    files=document['spec'].get('utilities',{}).get('director',{}).get('spec',{}).get('configFiles',{}).get('files',{})
    if 'director.ini' in files:
        files['director.ini']=native_director_ini(state.get('directorIni',files['director.ini']),state['worldPlan'],state.get('manualPins'),state.get('mapModes'))
    active=sum(len(desired_partitions(state,row)) for row in state['worldPlan']['maps'])
    document['spec']['stop']=state.get('desiredState')!='running'
    document['status']={'phase':'Ready' if state.get('desiredState')=='running' else 'Stopped','size':active,
                        'database':{'address':state['database']['name']+':5432','phase':'Ready'},'servers':[]}
    scales=[scale_resource(state,row) for row in state['worldPlan']['maps']]
    return {'world':world,'battlegroup':document,'scales':scales}


def parse_patch(state,name,patch):
    maps=[row for row in state['worldPlan']['maps'] if resource_name(state['worldId'],row['map'])==name]
    if len(maps)!=1:raise ValueError('The scaling resource is outside this installation.')
    map_info=maps[0];spec=scale_resource(state,map_info)['spec']
    if not isinstance(patch,list) or not 1<=len(patch)<=2:raise ValueError('Only a replica/partition patch is supported.')
    seen=set()
    for operation in patch:
        if not isinstance(operation,dict) or operation.get('op')!='replace' or set(operation)!={'op','path','value'}:
            raise ValueError('Unsupported scaling operation.')
        path=operation['path']
        if path not in {'/spec/replicas','/spec/partitions'} or path in seen:raise ValueError('Unsupported scaling field.')
        seen.add(path);spec[path.rsplit('/',1)[1]]=operation['value']
    partitions=spec['partitions'];replicas=spec['replicas']
    if type(replicas) is not int or not isinstance(partitions,list) or any(type(value) is not int for value in partitions):
        raise ValueError('Invalid map scaling values.')
    if len(set(partitions))!=len(partitions) or replicas!=len(partitions) or any(value not in map_info['partitions'] for value in partitions):
        raise ValueError('Replica and partition selection must match the installed map.')
    return map_info,partitions


def native_director_ini(source,plan,pins=None,modes=None):
    """Enable the stock demand scaler and retain explicit per-map warm floors."""
    pins=pins or {};lines=source.splitlines();sections={};current=None
    for index,line in enumerate(lines):
        match=re.fullmatch(r'\s*\[\s*([^\]]+?)\s*\]\s*',line)
        if match:current=match[1];sections.setdefault(current,[])
        if current is not None:sections[current].append(index)
    replacements={};additions={};extra=[]
    for row in plan['maps']:
        name=row['map'];floor=sum(1 for index,partition in enumerate(row['partitions'])
            if pins.get('game-'+str(partition),index<row['initialReplicas']))
        disabled=(modes or {}).get(name)=='disabled'
        desired={'EnableAutomaticInstanceScaling':'false' if disabled else 'true','MinServers':'0' if disabled else str(floor),'NumExtraServers':'0'}
        indexes=sections.get(name)
        if indexes is None:extra+=['','[ '+name+' ]']+[key+'='+value for key,value in desired.items()];continue
        found=set()
        for index in indexes:
            match=re.match(r'\s*([A-Za-z0-9_]+)\s*=',lines[index])
            if match and match[1] in desired:replacements[index]=match[1]+'='+desired[match[1]];found.add(match[1])
        additions[indexes[-1]]=[key+'='+value for key,value in desired.items() if key not in found]
    output=[]
    for index,line in enumerate(lines):
        output.append(replacements.get(index,line));output.extend(additions.get(index,[]))
    return '\n'.join(output+extra)+'\n'


def party_sharing_ini(source,map_name,shared):
    if map_name!='CB_Story_DestroyedZanovar' or type(shared) is not bool:
        raise ValueError('Choose the supported party-sharing map and a JSON boolean.')
    lines=source.splitlines(keepends=True);start=None;end=len(lines)
    for index,line in enumerate(lines):
        header=re.fullmatch(r'\s*\[\s*([^\]]+?)\s*\]\s*',line)
        if header:
            if start is not None:end=index;break
            if header[1]==map_name:start=index
    if start is None:raise ValueError('The map is missing from director settings.')
    eol='\r\n' if '\r\n' in source else '\n'
    section=[line for line in lines[start+1:end] if not re.match(r'\s*MaxParties\s*=',line,re.IGNORECASE)]
    if not shared:section.insert(0,'MaxParties=1'+eol)
    header=lines[start]
    if section and not header.endswith(('\r','\n')):header+=eol
    return ''.join(lines[:start]+[header]+section+lines[end:])
