"""Read the stock Funcom world definition; preserve its map catalogue."""
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re

REGIONS = ['Asia','Europe','North America','Oceania','South America']


def validate_profile(value):
    name=value.get('name','')
    if not isinstance(name,str) or not 1<=len(name)<=50 or any(ord(c)<32 for c in name):
        raise ValueError('World name must contain 1–50 printable characters.')
    region=value.get('region','')
    if region not in REGIONS: raise ValueError('Choose a supported world region.')
    address=value.get('address','')
    if not isinstance(address,str) or not address or len(address)>253: raise ValueError('Enter the server address.')
    try: ipaddress.ip_address(address)
    except ValueError:
        labels=address.removesuffix('.').split('.')
        if not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',label) for label in labels):
            raise ValueError('Enter a valid IP address or hostname.')
    base=value.get('gamePortBase',7777)
    if type(base) is not int or not 1024<=base<=65535: raise ValueError('Choose a valid game-port base.')
    return {'name':name,'region':region,'address':address,'gamePortBase':base}


def read_template(path=Path('/assets/server/scripts/setup/templates/world-template.yaml')):
    import yaml
    raw=path.read_text(encoding='utf-8')
    replaced=re.sub(r'\{[A-Z_]+\}',lambda match:'dst-template-placeholder',raw)
    world=yaml.safe_load(replaced)
    if world.get('kind')!='BattleGroup': raise ValueError('Official world template kind is unsupported.')
    deployment=world['spec']['database']['template']['spec']['deployment']['spec']
    rows=[]
    seen=set()
    for group in deployment['worldPartitions']:
        map_name=group['map']
        if not re.fullmatch(r'[A-Za-z0-9_]+',map_name): raise ValueError('Invalid map identifier in official template.')
        for partition in group['partitions']:
            identifier=partition['id']
            if type(identifier) is not int or identifier<=0 or identifier in seen: raise ValueError('Invalid or duplicate official partition.')
            seen.add(identifier)
            box={key:partition[source] for key,source in [('min_x','minX'),('min_y','minY'),('max_x','maxX'),('max_y','maxY')]}
            if any(type(value) not in {int,float} or not math.isfinite(value) for value in box.values()): raise ValueError('Invalid partition bounds.')
            if box['min_x']>box['max_x'] or box['min_y']>box['max_y']: raise ValueError('Invalid partition bounds order.')
            dimension=partition.get('dimension',0)
            blocked=partition.get('disable',False)
            if type(dimension) is not int or dimension<0 or type(blocked) is not bool: raise ValueError('Invalid partition properties.')
            rows.append({'id':identifier,'map':map_name,'dimension':dimension,
                         'blocked':blocked,'definition':{'type':'box2d_array','box':box}})
    if not rows: raise ValueError('Official template contains no world partitions.')
    return {'sha256':hashlib.sha256(raw.encode('utf-8')).hexdigest(),'partitions':sorted(rows,key=lambda row:row['id']), 'world':world}


def fresh_partition_sql(rows):
    statements=['BEGIN; SET LOCAL search_path TO dune,public;',
                "DO $$BEGIN IF EXISTS (SELECT 1 FROM dune.world_partition) THEN RAISE EXCEPTION 'World partitions already exist; refusing to overwrite them'; END IF; END$$;"]
    for row in rows:
        definition=json.dumps(row['definition'],separators=(',',':'))
        map_name=row['map'].replace("'","''")
        statements.append("INSERT INTO dune.world_partition(partition_id,map,partition_definition,dimension_index,blocked) VALUES ("+
                          str(row['id'])+",'"+map_name+"','"+definition+"'::jsonb,"+str(int(row['dimension']))+","+('true' if row['blocked'] else 'false')+");")
    statements.append("SELECT setval('dune.world_partition_partition_id_seq',(SELECT max(partition_id) FROM dune.world_partition)); COMMIT;")
    return '\n'.join(statements)
