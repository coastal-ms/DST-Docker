"""Narrow saved-INI I/O service. No network, shell execution or Docker socket."""
import hashlib
import base64
import json
import os
from pathlib import Path
import re
import socket
import socketserver
import stat
import struct
import tempfile
import threading
from datetime import datetime, timezone
import uuid

FILES={'game':'UserGame.ini','engine':'UserEngine.ini','server':'UserServerCustomSettings.ini','startup':'.dst-startup-exec-commands'}
MAX_FILE=1024*1024
MAX_WIRE=4*MAX_FILE
SOCKET=Path('/control/settings/settings.sock')


class SettingsConflict(ValueError):pass


class SavedSettings:
    def __init__(self,saved=Path('/saved')):
        self.saved=Path(saved).resolve()
        self.lock=threading.Lock()

    def root(self):
        root=self.saved/'UserSettings'
        if root.is_symlink() or not root.is_dir() or root.resolve().parent!=self.saved:
            raise ValueError('The authoritative UserSettings directory is missing or unsupported. No setup defaults were substituted.')
        return root

    def path(self,key):
        if not isinstance(key,str) or key not in FILES:raise ValueError('Choose a supported server INI file.')
        path=self.root()/FILES[key]
        if path.is_symlink():raise ValueError('Server INI symbolic links are not supported.')
        return path

    def map_store(self,target,create=False):
        if not isinstance(target,str) or not re.fullmatch(r'[1-9][0-9]{0,5}',target):
            raise ValueError('Choose a valid map partition.')
        root=self.root()
        for name in ('.dst-map-settings',target):
            root=root/name
            if root.is_symlink() or (root.exists() and not root.is_dir()):
                raise ValueError('The map settings directory is unsupported.')
            if create:root.mkdir(mode=0o700,exist_ok=True)
        if create:(root/'UserSettings').mkdir(mode=0o700,exist_ok=True)
        return SavedSettings(root)

    def map_read(self,target,key):
        if not isinstance(key,str) or key not in {'game','engine','server'}:raise ValueError('Choose a supported map INI file.')
        global_file=self.read(key)
        store=self.map_store(target)
        local=store.read(key) if (store.saved/'UserSettings').exists() else None
        overridden=bool(local and local['fileExists'])
        effective=local if overridden else global_file
        # Bind a draft to its source as well as its bytes: creating/removing an
        # identical override must invalidate a concurrent inherited draft too.
        revision=hashlib.sha256(json.dumps([overridden,effective['fileExists'],effective['revision']],separators=(',',':')).encode()).hexdigest()
        return {**effective,'revision':revision,'overridden':overridden,'target':target}

    def map_write(self,request):
        target=request.get('target');key=request.get('file')
        inherit=request.get('inherit',False)
        if type(inherit) is not bool:raise ValueError('The inheritance choice must be a boolean.')
        with self.lock:
            before=self.map_read(target,key)
            if before['revision']!=request.get('revision'):
                raise SettingsConflict('The selected map settings changed. Refresh before saving; your draft was not written.')
            store=self.map_store(target,create=True)
            local=store.read(key)
            def source_guard():
                if self.map_read(target,key)['revision']!=before['revision']:
                    raise SettingsConflict('The selected map settings source changed before replacement. Refresh and retry.')
            result=store.write(key,'' if inherit else request.get('raw'),local['revision'],local['fileExists'],remove=inherit,source_guard=source_guard)
            return {**self.map_read(target,key),'backup':result['backup'],'changed':result['changed'],'restartRequired':True}

    def read(self,key):
        path=self.path(key)
        exists=path.exists()
        before=path.stat() if exists else None
        if exists and (not stat.S_ISREG(before.st_mode) or before.st_size>MAX_FILE):raise ValueError('The server INI file is unsupported or exceeds 1 MiB.')
        if exists:
            descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(descriptor,'rb') as stream:
                opened=os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or (opened.st_ino,opened.st_dev)!=(before.st_ino,before.st_dev):
                    raise SettingsConflict('The server INI changed during read. Refresh and retry.')
                data=stream.read(MAX_FILE+1)
            if len(data)>MAX_FILE:raise ValueError('The server INI exceeds 1 MiB.')
        else:data=b''
        after=path.stat() if exists else None
        if exists and (before.st_ino,before.st_mtime_ns,before.st_size)!=(after.st_ino,after.st_mtime_ns,after.st_size):
            raise SettingsConflict('The server INI changed during read. Refresh and retry.')
        return {'file':key,'fileExists':exists,'raw':data.decode('utf-8'),'revision':hashlib.sha256(data).hexdigest(),
                'bytes':len(data),'modifiedAt':datetime.fromtimestamp(after.st_mtime,timezone.utc).isoformat() if exists else ''}

    def write(self,key,raw,revision,expected_exists,remove=False,source_guard=None):
        if not isinstance(raw,str) or len(raw.encode('utf-8'))>MAX_FILE:raise ValueError('Server INI content must be UTF-8 text no larger than 1 MiB.')
        if not isinstance(revision,str) or not re.fullmatch(r'[a-f0-9]{64}',revision):raise ValueError('A current server INI revision is required.')
        if type(expected_exists) is not bool or type(remove) is not bool:raise ValueError('The current file existence and removal choice are required.')
        with self.lock:
            before=self.read(key)
            if before['revision']!=revision or before['fileExists']!=expected_exists:raise SettingsConflict('The server INI changed. Refresh and retry; no settings were overwritten.')
            if before['fileExists'] and not remove and before['raw']==raw or not before['fileExists'] and remove:
                return {**before,'changed':False,'backup':''}
            root=self.root();path=self.path(key)
            backup=self.backup_snapshot(key,before) if before['fileExists'] else ''
            data=raw.encode('utf-8');temporary=None
            try:
                descriptor,temporary=tempfile.mkstemp(prefix='.dst-'+FILES[key]+'-',dir=root)
                with os.fdopen(descriptor,'wb') as stream:
                    stream.write(data);stream.flush();os.fsync(stream.fileno())
                if before['fileExists']:os.chmod(temporary,stat.S_IMODE(path.stat().st_mode))
                current=self.read(key)
                if current['revision']!=revision or current['fileExists']!=expected_exists:
                    raise SettingsConflict('The server INI changed before replacement. Refresh and retry.')
                if source_guard:source_guard()
                if remove:path.unlink(missing_ok=True)
                else:os.replace(temporary,path);temporary=None
                descriptor=os.open(root,os.O_RDONLY)
                try:os.fsync(descriptor)
                finally:os.close(descriptor)
            finally:
                if temporary is not None:Path(temporary).unlink(missing_ok=True)
            after=self.read(key)
            if after['revision']!=hashlib.sha256(b'' if remove else data).hexdigest() or after['fileExists']==remove:
                raise SettingsConflict('Saved INI readback changed. Check the current file before retrying.')
            return {**after,'changed':True,'backup':backup}

    def dispatch(self,request):
        if isinstance(request,dict) and request.get('action')=='maps.read':
            return self.map_read(request.get('target'),request.get('file'))
        if isinstance(request,dict) and request.get('action')=='maps.write':
            return self.map_write(request)
        if not isinstance(request,dict):raise ValueError('A settings request is required.')
        if request.get('action')=='read':return self.read(request.get('file'))
        if request.get('action')=='write':return self.write(request.get('file'),request.get('raw'),request.get('revision'),request.get('expectedExists'),request.get('remove',False))
        if request.get('action')=='backups.list':return self.backups()
        if request.get('action')=='backups.delete':return self.delete_backups(request.get('paths'))
        if request.get('action')=='backups.create':return self.backup_files(request.get('files'))
        if request.get('action')=='backups.inspect':return self.inspect_backups()
        if request.get('action')=='backups.read':
            if not isinstance(request.get('sha256'),str) or not re.fullmatch(r'[a-f0-9]{64}',request['sha256']):raise ValueError('A current INI backup checksum is required.')
            with self.lock:
                _,data=self.checked_backup(request.get('path'),request.get('sha256'))
                return {'base64':base64.b64encode(data).decode('ascii')}
        if request.get('action')=='backups.delete-checked':return self.delete_checked_backups(request.get('files'))
        raise ValueError('Unsupported settings action.')

    def checked_backup(self,path,expected=None):
        prefix='/srv/UserSettings/.dst-backups/'
        if not isinstance(path,str) or not path.startswith(prefix) or not re.fullmatch(r'User(?:Game|Engine|ServerCustomSettings)\.ini-\d{8}T\d{6}Z-[a-f0-9]{12}\.bak',path[len(prefix):]):
            raise ValueError('Choose a recognized server INI backup.')
        root=self.root()/'.dst-backups'
        if root.is_symlink() or not root.is_dir():raise ValueError('The settings backup directory is unsupported.')
        target=root/path[len(prefix):]
        descriptor=os.open(target,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(descriptor,'rb') as stream:
            before=os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size>MAX_FILE:raise ValueError('The server INI backup is unsupported or exceeds 1 MiB.')
            data=stream.read(MAX_FILE+1)
            after=os.fstat(stream.fileno())
        current=target.lstat()
        identity=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
        if len(data)>MAX_FILE or identity(before)!=identity(after) or identity(before)!=identity(current):
            raise SettingsConflict('The server INI backup changed. Refresh and retry.')
        digest=hashlib.sha256(data).hexdigest()
        if expected is not None and (not isinstance(expected,str) or not re.fullmatch(r'[a-f0-9]{64}',expected) or expected!=digest):
            raise SettingsConflict('The server INI backup changed. Refresh and retry.')
        return {'path':path,'name':target.name,'folder':'UserSettings/.dst-backups','size':len(data),'modified':int(before.st_mtime),'sha256':digest},data

    def inspect_backups(self):
        with self.lock:
            root=self.root()/'.dst-backups'
            if root.is_symlink():raise ValueError('The settings backup directory is unsupported.')
            if not root.exists():return {'backups':[]}
            result=[]
            for path in root.iterdir():
                if not re.fullmatch(r'User(?:Game|Engine|ServerCustomSettings)\.ini-\d{8}T\d{6}Z-[a-f0-9]{12}\.bak',path.name) or path.is_symlink():continue
                row,_=self.checked_backup('/srv/UserSettings/.dst-backups/'+path.name)
                result.append(row)
                if len(result)>500:raise ValueError('More than 500 server INI backups are present. Use the server file browser to archive older backups first.')
            return {'backups':sorted(result,key=lambda row:(row['modified'],row['name']),reverse=True)}

    def delete_checked_backups(self,files):
        if not isinstance(files,list) or not 1<=len(files)<=500 or any(not isinstance(row,dict) for row in files):raise ValueError('Select between 1 and 500 INI backups.')
        paths=[row.get('path') for row in files]
        if any(not isinstance(path,str) for path in paths) or len(set(paths))!=len(paths):raise ValueError('Invalid or duplicate INI backup selection.')
        if any(not re.fullmatch(r'/srv/UserSettings/\.dst-backups/User(?:Game|Engine|ServerCustomSettings)\.ini-\d{8}T\d{6}Z-[a-f0-9]{12}\.bak',row['path']) or not isinstance(row.get('sha256'),str) or not re.fullmatch(r'[a-f0-9]{64}',row['sha256']) for row in files):
            raise ValueError('A recognized INI backup path and current checksum are required.')
        with self.lock:
            results=[]
            for row in files:
                if not isinstance(row.get('sha256'),str) or not re.fullmatch(r'[a-f0-9]{64}',row['sha256']):raise ValueError('A current INI backup checksum is required.')
                try:
                    checked,_=self.checked_backup(row['path'],row['sha256'])
                    target=self.root()/'.dst-backups'/checked['name']
                    target.unlink()
                    results.append({'path':row['path'],'ok':True})
                except (SettingsConflict,FileNotFoundError):results.append({'path':row['path'],'ok':False})
            root=self.root()/'.dst-backups'
            descriptor=os.open(root,os.O_RDONLY)
            try:os.fsync(descriptor)
            finally:os.close(descriptor)
            return {'deleted':sum(row['ok'] for row in results),'results':results}

    def backup_snapshot(self,key,before):
        backups=self.root()/'.dst-backups'
        if backups.is_symlink():raise ValueError('The settings backup directory is unsupported.')
        backups.mkdir(mode=0o700,exist_ok=True)
        backup=FILES[key]+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:12]+'.bak'
        data=before['raw'].encode('utf-8')
        with (backups/backup).open('xb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        (backups/backup).chmod(0o600)
        if (backups/backup).read_bytes()!=data:raise ValueError('The settings before-image could not be verified.')
        descriptor=os.open(backups,os.O_RDONLY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
        return backup

    def backup_files(self,keys):
        if not isinstance(keys,list) or not keys or len(keys)>2 or any(not isinstance(key,str) or key not in {'game','engine'} for key in keys):
            raise ValueError('Choose the game and engine settings files to back up.')
        with self.lock:
            snapshots={key:self.read(key) for key in keys}
            result=[]
            for key,before in snapshots.items():
                backup=self.backup_snapshot(key,before) if before['fileExists'] else None
                result.append({'file':key,'path':'/srv/UserSettings/'+FILES[key],
                               'backup':'/srv/UserSettings/.dst-backups/'+backup if backup else None,
                               'ok':bool(backup),'reason':'' if backup else 'source file not found'})
            return {'timestamp':datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S'),'source':'live','files':result}

    def backups(self):
        root=self.root()/'.dst-backups'
        if root.is_symlink():raise ValueError('The settings backup directory is unsupported.')
        result=[]
        if not root.is_dir():return result
        for path in root.iterdir():
            matched=re.fullmatch(r'(UserGame|UserEngine)\.ini-(\d{8}T\d{6}Z)-[a-f0-9]{12}\.bak',path.name)
            if not matched or path.is_symlink() or not path.is_file():continue
            metadata=path.stat()
            result.append({'file':'game' if matched[1]=='UserGame' else 'engine','name':path.name,
                           'path':'/srv/UserSettings/.dst-backups/'+path.name,'dir':'/srv/UserSettings/.dst-backups',
                           'stamp':matched[2],'size':metadata.st_size,'modified':int(metadata.st_mtime)})
        return sorted(result,key=lambda row:(row['modified'],row['name']),reverse=True)

    def delete_backups(self,paths):
        if not isinstance(paths,list) or len(paths)>1000 or any(not isinstance(path,str) for path in paths):
            raise ValueError('Choose up to 1000 settings backup paths.')
        with self.lock:
            allowed={row['path']:row for row in self.backups()};results=[]
            for path in paths:
                entry=allowed.get(path)
                if not entry:results.append({'path':path,'ok':False,'reason':'not a recognized settings backup path'});continue
                target=self.root()/'.dst-backups'/entry['name']
                if target.is_symlink():raise ValueError('The settings backup file is unsupported.')
                target.unlink(missing_ok=True)
                results.append({'path':path,'ok':not target.exists()})
            return {'deleted':sum(row['ok'] for row in results),'results':results}


def authorize_peer(uid):
    if uid not in {0,10001}:raise ValueError('This service identity cannot access server settings.')


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(15)
        try:
            _,uid,_=struct.unpack('3i',self.connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            authorize_peer(uid)
            raw=self.rfile.readline(MAX_WIRE+1)
            if len(raw)>MAX_WIRE:raise ValueError('Settings request exceeds its limit.')
            result={'ok':True,'data':self.server.store.dispatch(json.loads(raw))}
        except SettingsConflict as error:result={'ok':False,'conflict':True,'error':str(error)}
        except (ValueError,UnicodeError) as error:result={'ok':False,'error':str(error)}
        except OSError:result={'ok':False,'error':'The saved server INI could not be accessed.'}
        self.wfile.write(json.dumps(result,ensure_ascii=False).encode()+b'\n')


if __name__=='__main__':
    if SOCKET.exists():SOCKET.unlink()
    server=socketserver.UnixStreamServer(str(SOCKET),Handler)
    SOCKET.chmod(0o660)
    server.store=SavedSettings()
    server.serve_forever()
