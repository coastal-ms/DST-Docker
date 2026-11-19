"""Copy verified backups into the configured host folder. Never deletes backups."""
import fcntl,hashlib,json,os,re,stat,time
from pathlib import Path

def copy_backups(source,destination,request):
    if (not isinstance(request,dict) or not re.fullmatch(r'[a-f0-9]{32}',str(request.get('id',''))) or
        not re.fullmatch(r'[a-f0-9]{32}',str(request.get('project',''))) or not isinstance(request.get('files'),list) or not 1<=len(request['files'])<=100):
        raise ValueError('Choose a bounded mirror batch from this world.')
    seen=set()
    for row in request['files']:
        if (not isinstance(row,dict) or not re.fullmatch(r'(?:backup-[0-9]+-[a-f0-9]{8}\.(?:backup|dump)|sh-[a-z0-9][a-z0-9-]{0,52}-[a-z]{6}-[0-9]{8}-[0-9]{6}\.backup)',str(row.get('name',''))) or
            not re.fullmatch(r'[a-f0-9]{64}',str(row.get('sha256',''))) or type(row.get('bytes')) is not int or row['bytes']<=0 or row['name'] in seen):
            raise ValueError('Mirror entries must match recorded native backups.')
        seen.add(row['name'])
    incoming=os.open(source,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    root=os.open(destination,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    out=None;lock=None
    try:
        marker=os.open('.dst-backup-mirror.json',os.O_RDONLY|os.O_NOFOLLOW,dir_fd=root)
        with os.fdopen(marker,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>4096:raise ValueError('The host backup folder marker needs review.')
            value=json.load(stream)
        if value.get('format')!=1 or value.get('composeProject')!=request.get('composeProject'):raise ValueError('The mirror folder belongs to another installation.')
        owner=os.fstat(root);folder='world-'+request['project']
        try:
            os.mkdir(folder,mode=0o700,dir_fd=root);os.chown(folder,owner.st_uid,owner.st_gid,dir_fd=root,follow_symlinks=False)
        except FileExistsError:pass
        out=os.open(folder,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=root)
        lock=os.open('.dst-mirror.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600,dir_fd=out)
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        reports=[]
        for row in request['files']:
            try:existing=os.open(row['name'],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=out)
            except FileNotFoundError:existing=None
            if existing is not None:
                with os.fdopen(existing,'rb') as stream:
                    before=os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size!=row['bytes']:raise ValueError('An existing mirror copy differs and was preserved.')
                    digest=hashlib.file_digest(stream,'sha256').hexdigest();after=os.fstat(stream.fileno())
                if (not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size!=row['bytes'] or digest!=row['sha256'] or
                    (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns)):
                    raise ValueError('An existing mirror copy differs. It was preserved; choose a separate folder or review it manually.')
                reports.append({**row,'copied':False});continue
            temporary='.dst-mirror-'+request['id']+'-'+row['name']+'.partial'
            try:
                previous=os.stat(temporary,dir_fd=out,follow_symlinks=False)
                if not stat.S_ISREG(previous.st_mode) or previous.st_nlink!=1:raise ValueError('An interrupted mirror copy needs review.')
                os.unlink(temporary,dir_fd=out)
            except FileNotFoundError:pass
            fd=os.open(row['name'],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=incoming)
            try:
                before=os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size!=row['bytes']:raise ValueError('The source backup changed before copying.')
                target=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=out)
                digest=hashlib.sha256();size=0
                with os.fdopen(target,'wb') as stream:
                    os.fchown(stream.fileno(),owner.st_uid,owner.st_gid)
                    while chunk:=os.read(fd,1024*1024):
                        stream.write(chunk);digest.update(chunk);size+=len(chunk)
                        if size>row['bytes']:raise ValueError('The source backup grew during copying.')
                    stream.flush();os.fsync(stream.fileno())
                after=os.fstat(fd)
                if digest.hexdigest()!=row['sha256'] or size!=row['bytes'] or (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError('The source backup failed its mirror integrity check.')
                os.link(temporary,row['name'],src_dir_fd=out,dst_dir_fd=out,follow_symlinks=False)
                os.unlink(temporary,dir_fd=out);os.fsync(out)
                reports.append({**row,'copied':True})
            except Exception:
                try:os.unlink(temporary,dir_fd=out)
                except FileNotFoundError:pass
                raise
            finally:os.close(fd)
        return {'mode':'mirror','id':request['id'],'attempt':request.get('attempt',0),'project':request['project'],'files':reports}
    finally:
        if lock is not None:os.close(lock)
        if out is not None:os.close(out)
        os.close(root);os.close(incoming)

def main():
    os.umask(0o077);result={'ok':False,'startedAt':time.time()}
    try:result.update(copy_backups('/backups','/mirror',json.loads(os.environ['DST_BACKUP_MIRROR'])));result['ok']=True
    except Exception:result['error']='The mirror copy needs review. Existing mirror files and the original backups were preserved.'
    result['finishedAt']=time.time();Path('/tmp/dst-result.json').write_text(json.dumps(result))
    return 0 if result['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
