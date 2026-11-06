"""Narrow saved-INI I/O service. No network, shell execution or Docker socket."""
import hashlib
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

    def write(self,key,raw,revision,expected_exists,remove=False):
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
        if not isinstance(request,dict):raise ValueError('A settings request is required.')
        if request.get('action')=='read':return self.read(request.get('file'))
        if request.get('action')=='write':return self.write(request.get('file'),request.get('raw'),request.get('revision'),request.get('expectedExists'),request.get('remove',False))
        if request.get('action')=='backups.list':return self.backups()
        if request.get('action')=='backups.delete':return self.delete_backups(request.get('paths'))
        if request.get('action')=='backups.create':return self.backup_files(request.get('files'))
        raise ValueError('Unsupported settings action.')

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
