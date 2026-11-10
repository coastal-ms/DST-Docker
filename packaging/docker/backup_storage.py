"""Fixed backup-volume operations for a networkless, socketless helper job."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

NAME = re.compile(r'backup-[0-9]+-[a-f0-9]{8}\.dump\Z')


def export(root,directory,request):
    if (not isinstance(request,dict) or not isinstance(request.get('name'),str) or not NAME.fullmatch(request['name']) or
        not re.fullmatch(r'[a-f0-9]{32}',str(request.get('id',''))) or
        not re.fullmatch(r'[a-f0-9]{64}',str(request.get('sha256','')))):
        raise ValueError('Choose a recorded backup export.')
    source=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    output=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    fd=None;temporary=request['id']+'.partial';destination=request['id']+'.dump'
    try:
        fd=os.open(request['name'],os.O_RDONLY|os.O_NOFOLLOW,dir_fd=source)
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('Backup storage contains an unsafe file.')
        if info.st_size!=request.get('bytes'):raise ValueError('Backup size no longer matches its record.')
        digest=hashlib.sha256();total=0
        target=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644,dir_fd=output)
        try:
            with os.fdopen(target,'wb') as stream:
                os.fchmod(stream.fileno(),0o644)
                while chunk:=os.read(fd,1024*1024):
                    digest.update(chunk);stream.write(chunk);total+=len(chunk)
                stream.flush();os.fsync(stream.fileno())
            after=os.fstat(fd)
            if digest.hexdigest()!=request['sha256'] or (info.st_size,info.st_mtime_ns,info.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                raise ValueError('Backup changed during export.')
            os.link(temporary,destination,src_dir_fd=output,dst_dir_fd=output,follow_symlinks=False)
            os.unlink(temporary,dir_fd=output);os.fsync(output)
        except Exception:
            try:os.unlink(temporary,dir_fd=output)
            except FileNotFoundError:pass
            raise
        return {'id':request['id'],'name':request['name'],'bytes':total,'sha256':digest.hexdigest()}
    finally:
        if fd is not None:os.close(fd)
        os.close(source);os.close(output)


def remove(root, files):
    if not isinstance(files,list) or not 1 <= len(files) <= 100:
        raise ValueError('Select between one and100 known backup files.')
    # Validate every supplied name before considering any unlink.
    names=set()
    for row in files:
        if not isinstance(row,dict) or not isinstance(row.get('name'),str) or not NAME.fullmatch(row['name']):
            raise ValueError('Choose an owned backup filename.')
        if row['name'] in names or not isinstance(row.get('sha256'),str) or not re.fullmatch(r'[a-f0-9]{64}',row['sha256']):
            raise ValueError('Choose distinct backups with saved checksums.')
        names.add(row['name'])
    directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    deleted=[]
    try:
        # Hash and hold each exact file before deleting anything. A changed,
        # linked or unexpected file blocks the entire batch.
        opened=[]
        try:
            for row in files:
                try:fd=os.open(row['name'],os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
                except FileNotFoundError:
                    opened.append((row,None,None));continue
                opened.append((row,fd,None))
                info=os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('Backup storage contains an unsafe file.')
                digest=hashlib.sha256()
                while chunk:=os.read(fd,1024*1024):digest.update(chunk)
                after=os.fstat(fd)
                if digest.hexdigest()!=row['sha256'] or (info.st_size,info.st_mtime_ns,info.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                    raise ValueError('A backup changed; existing files were preserved.')
                opened[-1]=(row,fd,after)
            for row,fd,info in opened:
                if fd is not None:
                    current=os.stat(row['name'],dir_fd=directory,follow_symlinks=False)
                    if (current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns,current.st_ctime_ns)!=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns):
                        raise ValueError('Backup storage changed before deletion.')
                    os.unlink(row['name'],dir_fd=directory)
                # Missing files are an idempotent retry of this exact journaled
                # batch, never permission to delete a replacement name.
                deleted.append(row['name'])
            os.fsync(directory)
        finally:
            for _,fd,_ in opened:
                if fd is not None:os.close(fd)
    finally:os.close(directory)
    return deleted


def main():
    result={'ok':False,'startedAt':time.time()}
    try:
        if os.environ.get('DST_BACKUP_EXPORT'):
            request=json.loads(os.environ['DST_BACKUP_EXPORT'])
            result.update(export('/backups','/exports',request))
        else:
            request=json.loads(os.environ['DST_BACKUP_FILES'])
            result['deleted']=remove('/backups',request)
        result['ok']=True
    except Exception:
        result['error']='Backup cleanup could not be verified. Review retained records before retrying.'
    result['finishedAt']=time.time()
    Path('/tmp/dst-result.json').write_text(json.dumps(result))
    return 0 if result['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
