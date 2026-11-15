"""Derive native Docker topology from the installed official world template.

Pure planning only: no Docker calls, secret reads, registration or mutations.
Keep every stock map in the catalogue, including maps with zero initial replicas.
"""
import re
from world_template import validate_profile

OFFICIAL='registry.funcom.com/funcom/self-hosting/'
COMPONENTS={
    'director':('battlegroup/server-bg-director.tar','seabass-server-bg-director'),
    'text-router':('battlegroup/server-text-router.tar','seabass-server-text-router'),
    'gateway':('battlegroup/server-gateway.tar','seabass-server-gateway'),
    'rmq-admin':('battlegroup/server-rabbitmq.tar','seabass-server-rabbitmq'),
    'rmq-game':('battlegroup/server-rabbitmq.tar','seabass-server-rabbitmq'),
    'game':('battlegroup/server.tar','seabass-server'),
}


def official_images(assets):
    result={}
    for component,(archive,name) in COMPONENTS.items():
        tags=[tag for entry in assets['images'] if entry['archive']==archive for tag in entry['tags']]
        if len(tags)!=1 or not re.fullmatch(re.escape(OFFICIAL+name)+r':[A-Za-z0-9_.-]+',tags[0]):
            raise ValueError('A required official server image is unavailable.')
        result[component]={'image':tags[0],'archive':'/assets/server/images/'+archive}
    return result


def memory_bytes(value):
    match=re.fullmatch(r'([1-9][0-9]*)(Ki|Mi|Gi|Ti)?',str(value))
    if not match: raise ValueError('Unsupported official memory limit.')
    return int(match[1])*{'Ki':1024,'Mi':1024**2,'Gi':1024**3,'Ti':1024**4,None:1}[match[2]]


def plan_world(project,profile,template,assets,database,memory_overrides=None,swap_policy=None):
    if not re.fullmatch(r'[a-f0-9]{32}',project): raise ValueError('Invalid project identity.')
    profile=validate_profile(profile)
    images=official_images(assets)
    prefix='dst-'+project+'-'
    if database.get('network')!=prefix+'network' or database.get('name')!=prefix+'postgres':
        raise ValueError('World database does not belong to this installation.')
    base=profile['gamePortBase']
    ports={key:base+offset for key,offset in {'director':1000,'rmq-admin':1001,
                                            'rmq-game-http':1003,'text-router':1004}.items()}
    # Existing custom installations retain their ports until Settings applies
    # the standard player connection layout explicitly.
    ports['rmq-game']=31982 if base==7777 else base+1002
    sets=template['world']['spec']['serverGroup']['template']['spec']['sets']
    maps=[]
    names=set()
    for item in sets:
        name=item['map']
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_]+',name) or name in names:
            raise ValueError('Invalid official map catalogue.')
        names.add(name)
        partitions=[row['id'] for row in template['partitions'] if row['map']==name]
        if not partitions: raise ValueError('Official map has no world partition.')
        replicas=item['replicas']
        if type(replicas) is not int or replicas<0 or replicas>len(partitions):
            raise ValueError('Unsupported official initial replica count.')
        declared=item.get('partitions')
        if declared is not None and any(identifier not in partitions for identifier in declared):
            raise ValueError('Official map partition declarations disagree.')
        maps.append({'map':name,'partitions':partitions,'initialReplicas':replicas,
                     'memoryBytes':memory_bytes(item['resources']['limits']['memory'])})
    if names!={row['map'] for row in template['partitions']}:
        raise ValueError('Official map and partition catalogues disagree.')
    memory_overrides=memory_overrides or {}
    if not isinstance(memory_overrides,dict) or set(memory_overrides)-names:
        raise ValueError('Memory overrides must identify installed maps.')
    for row in maps:
        if row['map'] in memory_overrides:
            value=memory_overrides[row['map']]
            if type(value) is not int or value<256*1024**2 or value>128*1024**3:
                raise ValueError('Map memory must be between 256 MiB and 128 GiB.')
            row['memoryBytes']=value
    games=[{'partition':row['id'],'map':row['map'],'gamePort':base+row['id']-1,
            'igwPort':base+2000+row['id']-1} for row in template['partitions']]
    all_ports=list(ports.values())+[game[key] for game in games for key in ['gamePort','igwPort']]
    if any(port>65535 for port in all_ports) or len(all_ports)!=len(set(all_ports)):
        raise ValueError('Choose a lower game-port base; the world port ranges overlap or exceed 65535.')
    if database['port'] in all_ports:
        raise ValueError('World ports overlap the database port. Choose another game-port base.')
    return {'projectId':project,'templateSha256':template['sha256'],'profile':profile,'images':images,'memorySwap':swap_policy,
            'names':{key:prefix+key for key in COMPONENTS if key!='game'},'ports':ports,
            'maps':maps,'games':games,'network':database['network'],'databaseName':database['name'],'databasePort':database['port'],
            'initialMemoryBytes':sum(item['memoryBytes']*item['initialReplicas'] for item in maps)}


def public_plan(plan):
    return {key:plan[key] for key in ['templateSha256','ports','maps','games','initialMemoryBytes']}
