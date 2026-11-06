"""Local message-queue configuration from Funcom's installed template."""
import ipaddress
import subprocess


def ensure_tls(root,hostname,address):
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    manifest=root/'identity'
    identity='2\n'+hostname+'\n'+address
    if manifest.exists():
        if manifest.read_text()!=identity: raise ValueError('Connection certificate address changed; stop and rebuild connection services first.')
        for name in ['ca.pem','cert.pem','key.pem']:
            if not (root/name).is_file(): raise ValueError('Connection certificate storage needs recovery.')
        return {name:(root/name).read_bytes() for name in ['ca.pem','cert.pem','key.pem']}
    # No shell expansion and no key material or credentials in command output.
    def run(*args):
        subprocess.run(['openssl',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
    run('req','-x509','-newkey','rsa:3072','-nodes','-sha256','-days','3650',
        '-subj','/CN=DST Local Connection CA','-addext','basicConstraints=critical,CA:TRUE',
        '-addext','keyUsage=critical,keyCertSign,cRLSign',
        '-keyout',str(root/'ca-key.pem'),'-out',str(root/'ca.pem'))
    run('req','-new','-newkey','rsa:3072','-nodes','-sha256','-subj','/CN='+hostname,
        '-keyout',str(root/'key.pem'),'-out',str(root/'request.pem'))
    names=['DNS:'+hostname,'DNS:localhost','IP:127.0.0.1']
    try: names.append('IP:'+str(ipaddress.ip_address(address)))
    except ValueError: names.append('DNS:'+address)
    extension=root/'extensions.cnf'
    extension.write_text('subjectAltName='+','.join(dict.fromkeys(names))+
                         '\nextendedKeyUsage=serverAuth\nbasicConstraints=critical,CA:FALSE\n'
                         'keyUsage=critical,digitalSignature,keyEncipherment\nauthorityKeyIdentifier=keyid,issuer\nsubjectKeyIdentifier=hash\n')
    run('x509','-req','-in',str(root/'request.pem'),'-CA',str(root/'ca.pem'),'-CAkey',str(root/'ca-key.pem'),
        '-CAcreateserial','-out',str(root/'cert.pem'),'-days','825','-sha256','-extfile',str(extension))
    for item in root.iterdir(): item.chmod(0o600)
    manifest.write_text(identity);manifest.chmod(0o600)
    return {name:(root/name).read_bytes() for name in ['ca.pem','cert.pem','key.pem']}


def queue_spec(component,plan,template,tls):
    role={'rmq-admin':'admin','rmq-game':'game'}[component]
    stock=next(item['spec'] for item in template['world']['spec']['utilities']['messageQueues']['templates']
               if item['metadata']['name']==role)
    config=stock['configs']['system'].replace('$(RMQ_AUTH_BACKEND_1)','cache').replace(
        '$(RMQ_HTTP_AUTH_ADDRESS)',plan['names']['text-router']+':5059')
    if '$(' in config: raise ValueError('Unsupported message-queue template substitution.')
    plugins=stock['plugins']['system']
    known={'rabbitmq_management','rabbitmq_prometheus','rabbitmq_auth_backend_http','rabbitmq_auth_backend_cache'}
    if set(plugins)!=known: raise ValueError('Unsupported official message-queue plugin configuration.')
    files={
        'etc/rabbitmq/rabbitmq.conf':{'data':config},
        'etc/rabbitmq/enabled_plugins':{'data':'['+','.join(plugins)+'].\n'},
    }
    ports=[{'container':5672,'host':plan['ports'][component],'ip':'127.0.0.1' if role=='admin' else '0.0.0.0'}]
    if role=='game':
        ports.append({'container':15672,'host':plan['ports']['rmq-game-http'],'ip':'127.0.0.1'})
        for target,source in [('cacert.pem','ca.pem'),('cert.pem','cert.pem'),('key.pem','key.pem')]:
            files['etc/rabbitmq/'+target]={'data':tls[source],'uid':100,'gid':101,'mode':0o400}
    return {'environment':{'RABBITMQ_NODENAME':'rabbit@'+plan['names'][component],
                           'RABBITMQ_DEFAULT_USER':'dst-unused','RABBITMQ_DEFAULT_PASS':'disabled-by-http-auth'},
            'ports':ports,'files':files,
            'volumes':[{'name':plan['names'][component]+'-data','target':'/var/lib/rabbitmq'}],
            'health':{'Test':['CMD','rabbitmq-diagnostics','-q','ping'],'Interval':10_000_000_000,
                      'Timeout':5_000_000_000,'Retries':12,'StartPeriod':20_000_000_000}}
