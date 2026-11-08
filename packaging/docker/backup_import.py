"""Stage an explicitly trusted PostgreSQL custom backup; never connects to a DB."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time


def import_file(source,destination,request):
    if (not isinstance(request,dict) or not re.fullmatch(r'[a-f0-9]{32}',str(request.get('uploadId',''))) or
        not re.fullmatch(r'backup-[0-9]+-[a-f0-9]{8}\.dump',str(request.get('name',''))) or
        not re.fullmatch(r'[a-f0-9]{64}',str(request.get('sha256',''))) or
        type(request.get('bytes')) is not int or not 5<=request['bytes']<=25*1024**3):
        raise ValueError('Choose a bounded PostgreSQL backup upload.')
    if shutil.disk_usage(destination).free<request['bytes']+512*1024**2:raise ValueError('Backup storage has insufficient space for the import.')
    incoming=os.open(source,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    output=os.open(destination,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    fd=None;temporary=request['name']+'.partial'
    try:
        fd=os.open(request['uploadId']+'.upload',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=incoming)
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size!=request['bytes']:
            raise ValueError('The selected upload changed or is not a regular file.')
        if os.read(fd,5)!=b'PGDMP':raise ValueError('Choose a PostgreSQL custom-format backup, not a SQL script or other file.')
        os.lseek(fd,0,os.SEEK_SET)
        target=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=output)
        digest=hashlib.sha256();total=0
        try:
            with os.fdopen(target,'wb') as stream:
                while chunk:=os.read(fd,1024*1024):digest.update(chunk);stream.write(chunk);total+=len(chunk)
                stream.flush();os.fsync(stream.fileno())
            after=os.fstat(fd)
            if digest.hexdigest()!=request['sha256'] or total!=request['bytes'] or (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                raise ValueError('The uploaded backup failed its integrity check.')
            # Catalog parsing does not execute the archive. Full restore
            # rehearsal remains a separate explicit verification operation.
            subprocess.run(['pg_restore','--list',str(Path(destination)/temporary)],check=True,timeout=120,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            os.link(temporary,request['name'],src_dir_fd=output,dst_dir_fd=output,follow_symlinks=False)
            os.unlink(temporary,dir_fd=output);os.fsync(output)
            return {'mode':'import','name':request['name'],'uploadId':request['uploadId'],'sha256':digest.hexdigest(),'bytes':total,'format':'postgresql-custom'}
        except Exception:
            try:os.unlink(temporary,dir_fd=output)
            except FileNotFoundError:pass
            raise
    finally:
        if fd is not None:os.close(fd)
        os.close(incoming);os.close(output)


def main():
    os.umask(0o077)
    result={'ok':False,'startedAt':time.time()}
    try:
        result.update(import_file('/incoming','/backups',json.loads(os.environ['DST_BACKUP_IMPORT'])))
        result['ok']=True
    except Exception:
        result['error']='The uploaded file is not a verified PostgreSQL custom archive or could not be copied safely. Existing backups and the world were preserved.'
    result['finishedAt']=time.time()
    Path('/tmp/dst-result.json').write_text(json.dumps(result))
    return 0 if result['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
