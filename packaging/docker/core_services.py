"""Native Funcom component adapters. No Kubernetes API or third-party patches."""
from pathlib import Path
import re


def service_specs(plan,template,credentials):
    identity=credentials['worldId']
    if not re.fullmatch(r'sh-[a-z0-9-]+',identity): raise ValueError('Invalid self-host world identity.')
    scaler=credentials.get('scaler')
    common={
        'BATTLEGROUP':identity,'BATTLEGROUP_NAME':identity,'FARM_NAME':identity,
        'BATTLEGROUP_DISPLAY_NAME':identity,'BATTLEGROUP_TITLE':plan['profile']['name'],
        'BATTLEGROUP_REGION_NAME':plan['profile']['region'],
        'FuncomLiveServices__ServiceAuthToken':credentials['token'],
        'FuncomLiveServices__RmqTlsEnabled':'true',
        'RMQ_HTTP_TOKEN_AUTH_SECRET':credentials['rmqSecret'],
        'fls-apikey':credentials['apiKey'],
        'HOST_DATACENTER_ID':'dune-testing','HOST_DATACENTER_IP_ADDRESS':plan['profile']['address'],
        'KUBERNETES_SERVICE_HOST':scaler['hostname'] if scaler else '127.0.0.1',
        'KUBERNETES_SERVICE_PORT':'8443' if scaler else '9','KUBERNETES_SERVICE_PORT_HTTPS':'8443' if scaler else '9',
        'DOTNET_HOSTBUILDER__RELOADCONFIGONCHANGE':'false',
    }
    database={'Database_address':plan['databaseName']+':5432','Database_name':'dune',
              'Database_user':'dune','Database_password':credentials['dbPassword']}
    rmq_args=['--RMQGameHostname='+plan['names']['rmq-game'],'--RMQGamePort=5672',
              '--RMQAdminHostname='+plan['names']['rmq-admin'],'--RMQAdminPort=5672']
    ca={'usr/local/share/ca-certificates/dst-connection.crt':{'data':credentials['tls']['ca.pem']},
        'run/secrets/kubernetes.io/serviceaccount/ca.crt':{'data':scaler['ca'] if scaler else credentials['tls']['ca.pem']},
        'run/secrets/kubernetes.io/serviceaccount/token':{'data':scaler['token'] if scaler else 'dst-native-no-kubernetes-api','mode':0o400},
        'run/secrets/kubernetes.io/serviceaccount/namespace':{'data':identity}}
    def wrapper(command):
        # Funcom's small .NET images include the trust bundle but omit the
        # distribution's update-ca-certificates utility. Build a public bundle
        # for this process without adding a package manager or changing stock CA.
        return {'data':'#!/bin/sh\nset -eu\n'
                'cat /etc/ssl/certs/ca-certificates.crt /usr/local/share/ca-certificates/dst-connection.crt > /tmp/dst-ca-bundle.pem\n'
                'export SSL_CERT_FILE=/tmp/dst-ca-bundle.pem\n'
                'export REQUESTS_CA_BUNDLE=/tmp/dst-ca-bundle.pem\n'
                'export CURL_CA_BUNDLE=/tmp/dst-ca-bundle.pem\n'
                'exec '+command+' "$@"\n','mode':0o555}
    director_ini=template['world']['spec']['utilities']['director']['spec']['configFiles']['files']['director.ini']
    result={
        'director':{'environment':{**common,**database,'ASPNETCORE_URLS':'http://0.0.0.0:11717'},
                    'command':rmq_args,'entrypoint':['/dst-component.sh'],
                    'ports':[{'container':11717,'host':plan['ports']['director'],'ip':'127.0.0.1'}],
                    'files':{**ca,'dst-component.sh':wrapper('./Director'),
                             'Tools/Battlegroups/Director/BattlegroupDirector/director_config.ini':{'data':director_ini}}},
        'text-router':{'environment':{**common,**database,'BATTLEGROUP_LANGUAGE':'en-US','ASPNETCORE_URLS':'http://0.0.0.0:5059'},
                       'command':rmq_args,'ports':[{'container':5059,'host':plan['ports']['text-router'],'ip':'127.0.0.1'}],
                       'entrypoint':['/dst-component.sh'],'files':{**ca,'dst-component.sh':wrapper('./TextRouter')}},
        'gateway':{'environment':{**common,'FuncomLiveServices__BattlegroupAuthorizationPreset':'BattlegroupInternal',
                    'DuneDatabaseInterfacePSQL_DatabaseHost':plan['databaseName']+':5432',
                    'DuneDatabaseInterfacePSQL_DatabaseName':'dune','DuneDatabaseInterfacePSQL_DatabaseUser':'dune',
                    'DuneDatabaseInterfacePSQL_DatabasePassword':credentials['dbPassword'],
                    'OnlineSubsystem_ServerName':identity,'OnlineSubsystem_DatacenterId':plan['profile']['region'],
                    'gateway_farm_api_key':credentials['apiKey'],'gateway_display_name':plan['profile']['name']},
                   'command':['python','-m','service','-c','./service/configs/service.conf',
                              '--RMQGameHostname='+plan['profile']['address'],'--RMQGamePort='+str(plan['ports']['rmq-game']),
                              '--RMQGameHttpPort='+str(plan['ports']['rmq-game-http'])],
                   'entrypoint':['/dst-component.sh'],
                   'files':{**ca,'dst-component.sh':wrapper('env')}}
    }
    return result


def game_spec(plan,partition,credentials,bridge_address,defaults):
    game=next(row for row in plan['games'] if row['partition']==partition)
    map_info=next(row for row in plan['maps'] if row['map']==game['map'])
    identity=credentials['worldId']
    arguments=[game['map'],'-FarmRegion='+plan['profile']['region'],
               '-ini:engine:[FuncomLiveServices]:ServiceAuthToken='+credentials['token'],
               '-RMQGameTlsEnabled=true','ServerName='+identity,'-MultiHome=0.0.0.0',
               '-ExternalAddress='+plan['profile']['address'],'-DatabaseName=dune',
               '-DatabaseHost=127.0.0.1:'+str(plan['databasePort']),'-DatabaseUser=dune',
               '-DatabasePassword='+credentials['dbPassword'],'-PartitionIndex='+str(partition),
               '-ini:engine:[URL]:Port='+str(game['gamePort']),'-ini:engine:[URL]:IGWPort='+str(game['igwPort']),
               '-IGWBindAddress='+bridge_address,'-battlegroup-director-url=127.0.0.1:'+str(plan['ports']['director']),
               '--RMQGameHostname=127.0.0.1','--RMQGamePort='+str(plan['ports']['rmq-game']),
               '--RMQAdminHostname=127.0.0.1','--RMQAdminPort='+str(plan['ports']['rmq-admin'])]
    files={'dst-game.sh':{'data':Path('/opt/dst-manager/native-game.sh').read_text(),'mode':0o555},
           'usr/local/share/ca-certificates/dst-connection.crt':{'data':credentials['tls']['ca.pem']}}
    # Settings are seeded only into a brand-new owned Saved volume. Later
    # updates must compare and explicitly preserve users' manual edits.
    for name,data in (defaults.items() if partition==1 else []):
        if name not in {'UserEngine.ini','UserGame.ini','UserServerCustomSettings.ini'}: raise ValueError('Invalid stock settings file.')
        files['home/dune/server/DuneSandbox/Saved/UserSettings/'+name]={'data':data,'uid':1000,'gid':65534,'mode':0o600}
    return {'environment':{'POD_UID':'dst-native-'+str(partition),'POD_NAME':'dst-'+plan['projectId']+'-game-'+str(partition),
                           'POD_IP':bridge_address,'SERVER_INDEX':str(partition),'FARM_NAME':identity,
                           'BATTLEGROUP_NAME':identity,'BATTLEGROUP':identity,'BATTLEGROUP_DISPLAY_NAME':identity,
                           'BATTLEGROUP_TITLE':plan['profile']['name'],'FuncomLiveServices__RmqTlsEnabled':'true',
                           'FuncomLiveServices__ServiceAuthToken':credentials['token'],
                           'RMQ_HTTP_TOKEN_AUTH_SECRET':credentials['rmqSecret'],'fls-apikey':credentials['apiKey']},
            'command':arguments,'entrypoint':['/dst-game.sh'],'host_network':True,'memory':map_info['memoryBytes'],'map_name':game['map'],
            'volumes':[{'name':'dst-'+plan['projectId']+'-game-'+str(partition)+'-saved',
                        'target':'/home/dune/server/DuneSandbox/Saved','mustBeNew':True}]+(
                       [{'name':'dst-'+plan['projectId']+'-game-1-saved','target':'/home/dune/server/DuneSandbox/Saved/UserSettings',
                         'subpath':'UserSettings'}] if partition!=1 else []),'files':files}
