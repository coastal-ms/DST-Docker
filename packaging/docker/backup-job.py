"""Owned PostgreSQL dump and restore rehearsal. Never replaces the live DB."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def run(*command,capture=False):
    result=subprocess.run(command,check=False,stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL,timeout=1800)
    if result.returncode:raise RuntimeError('PostgreSQL backup operation failed. The original database and backup files were preserved.')
    return result.stdout.decode('utf-8') if capture else ''


def main():
    os.umask(0o077)
    result={'ok':False,'startedAt':time.time()}
    try:
        mode=os.environ['DST_BACKUP_MODE'];name=os.environ['DST_BACKUP_NAME']
        if mode not in {'create','verify'} or not re.fullmatch(r'backup-[0-9]+-[a-f0-9]{8}\.dump',name):
            raise ValueError('Invalid owned backup job.')
        host=os.environ['DST_DATABASE_HOST']
        if not re.fullmatch(r'dst-[a-f0-9]{32}-postgres',host):raise ValueError('Invalid owned database.')
        os.environ.update(PGHOST=host,PGPORT='5432',PGUSER='postgres',PGCONNECT_TIMEOUT='10',
                          PGPASSWORD=Path('/run/dst/postgres-admin.password').read_text())
        target=Path('/backups')/name
        result.update(mode=mode,name=name)
        if mode=='create':
            partial=target.with_suffix('.partial')
            with partial.open('xb'):pass
            run('pg_dump','-Fc','-d','dune','-f',str(partial))
            run('pg_restore','--list',str(partial))
            partial.replace(target)
            result.update(sha256=digest(target),bytes=target.stat().st_size,format='postgresql-custom')
        else:
            expected=os.environ['DST_EXPECTED_SHA256']
            if not re.fullmatch(r'[a-f0-9]{64}',expected) or digest(target)!=expected:
                raise ValueError('The backup checksum does not match its saved record.')
            verification=os.environ['DST_VERIFY_DATABASE']
            retain=os.environ.get('DST_RETAIN_VERIFICATION')=='1'
            prefix='dst_qualify_' if retain else 'dst_verify_'
            if not re.fullmatch(prefix+r'[a-f0-9]{24}',verification):raise ValueError('Invalid restore rehearsal database.')
            result['verificationDatabase']=verification
            run('createdb','-O','dune',verification)
            run('pg_restore','--exit-on-error','-d',verification,str(target))
            report=run('psql','-X','-t','-A','-d',verification,'-v','ON_ERROR_STOP=1','-c',
                       "SELECT json_build_object('duneTables',(SELECT count(*) FROM information_schema.tables WHERE table_schema='dune' AND table_type='BASE TABLE'),'duneViews',(SELECT count(*) FROM information_schema.views WHERE table_schema='dune'),'partitions',(SELECT count(*) FROM dune.world_partition),'players',(SELECT count(*) FROM dune.player_state))",capture=True)
            counts=json.loads(report)
            if counts['duneTables']<=0:raise ValueError('The restored backup has no game schema.')
            if digest(target)!=expected:raise ValueError('The backup changed during the restore rehearsal.')
            # Only the generated verification DB is removed after success.
            # A failed rehearsal is retained for investigation, never swapped.
            if not retain:run('dropdb',verification)
            result.update(sha256=expected,restored=counts,verificationDatabaseRemoved=not retain,
                          verificationDatabaseRetained=retain)
        result['ok']=True
    except (ValueError,RuntimeError) as error:result['error']=str(error)
    except Exception:result['error']='The backup operation failed. The original database was preserved.'
    result['finishedAt']=time.time()
    Path('/tmp/dst-result.json').write_text(json.dumps(result))
    return 0 if result['ok'] else 1


if __name__=='__main__':sys.exit(main())
