"""Build a fresh-world archive in an isolated database; never replaces dune.

The manager prepends PARTITION_SQL from its validated official world template.
Only the later existing verified restore transaction may promote this archive.
"""
import hashlib,json,os,re,runpy,subprocess,sys,time,traceback
from pathlib import Path
import psycopg2
from psycopg2 import sql

REPORT=Path('/tmp/dst-result.json')

def checkpoint(result,phase):
    result.update(phase=phase,updatedAt=time.time())
    temporary=REPORT.with_suffix('.tmp');temporary.write_text(json.dumps(result));temporary.replace(REPORT)

def main():
    os.umask(0o077)
    result={'ok':False,'mode':'fresh-world','startedAt':time.time(),'liveDatabaseChanged':False}
    connection=None
    try:
        operation=os.environ['DST_OPERATION_ID'];host=os.environ['DST_DATABASE_HOST'];name=os.environ['DST_BACKUP_NAME']
        if not re.fullmatch(r'[a-f0-9]{32}',operation) or not re.fullmatch(r'dst-[a-f0-9]{32}-postgres',host):raise ValueError('Invalid owned fresh-world identity.')
        if not re.fullmatch(r'(?:backup-[0-9]+-[a-f0-9]{8}\.(?:backup|dump)|sh-[a-z0-9][a-z0-9-]{0,52}-[a-z]{6}-[0-9]{8}-[0-9]{6}\.backup)',name):raise ValueError('Invalid fresh-world archive name.')
        stage='dst_fresh_'+operation[:24]
        result.update(operationId=operation,name=name,stagingDatabase=stage)
        admin=Path('/run/dst/postgres-admin.password').read_text();password=Path('/run/dst/dune-app.password').read_text()
        connection=psycopg2.connect(host=host,port=5432,dbname='postgres',user='postgres',password=admin,connect_timeout=10)
        connection.autocommit=True
        target=Path('/backups')/name;partial=target.with_suffix('.partial')
        with connection.cursor() as cursor:
            cursor.execute('SELECT oid FROM pg_database WHERE datname=%s',(stage,))
            if cursor.fetchone() or target.exists() or partial.exists():raise ValueError('This fresh-world attempt has retained data; review it instead of rerunning it.')
            cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname='dune'")
            if cursor.fetchone()!=(False,):raise ValueError('The application role needs review before preparing a fresh world.')
            cursor.execute(sql.SQL('CREATE DATABASE {} OWNER dune').format(sql.Identifier(stage)))
            cursor.execute('SELECT oid FROM pg_database WHERE datname=%s',(stage,));result['stageOid']=cursor.fetchone()[0]
        checkpoint(result,'initializing-stage')
        with connection.cursor() as cursor:cursor.execute('ALTER ROLE dune SUPERUSER')
        try:
            sys.argv=['updatedb.py','--host',host+':5432','--project-database',stage,'--project-user','dune',
                      '--project-password',password,'--admin-user','postgres','--admin-password',admin,
                      '--admin-database','postgres','--postgres-installation','/usr','--unattended','--no-backup']
            sys.path.insert(0,'/root/PSQL')
            try:runpy.run_path('/root/PSQL/updatedb.py',run_name='__main__')
            except SystemExit as outcome:
                if outcome.code not in (None,0):raise RuntimeError('Official fresh schema initialization failed.') from None
        finally:
            with connection.cursor() as cursor:cursor.execute('ALTER ROLE dune NOSUPERUSER')
        checkpoint(result,'seeding-partitions')
        with psycopg2.connect(host=host,port=5432,dbname=stage,user='dune',password=password,connect_timeout=10) as fresh:
            with fresh.cursor() as cursor:
                cursor.execute(PARTITION_SQL)
                cursor.execute("SELECT json_build_object('duneTables',(SELECT count(*) FROM information_schema.tables WHERE table_schema='dune' AND table_type='BASE TABLE'),'duneViews',(SELECT count(*) FROM information_schema.views WHERE table_schema='dune'),'partitions',(SELECT count(*) FROM dune.world_partition),'players',(SELECT count(*) FROM dune.player_state))")
                counts=cursor.fetchone()[0]
                cursor.execute('SELECT (SELECT count(*) FROM dune.actors)+(SELECT count(*) FROM dune.accounts)')
                if counts['duneTables']<=0 or counts['players']!=0 or counts['partitions']<=0 or cursor.fetchone()[0]!=0:raise ValueError('The fresh schema contains unexpected gameplay records.')
        fresh.close()
        checkpoint(result,'exporting-stage')
        with partial.open('xb'):pass
        environment={**os.environ,'PGPASSWORD':admin,'PGCONNECT_TIMEOUT':'10'}
        subprocess.run(['/usr/bin/pg_dump','-h',host,'-U','postgres','-d',stage,'-Fc','-f',str(partial)],env=environment,check=True,timeout=1800,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run(['/usr/bin/pg_restore','--list',str(partial)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        with partial.open('rb') as stream:
            digest=hashlib.file_digest(stream,'sha256').hexdigest();os.fsync(stream.fileno())
        # No overwrite, including a file created by an external operator.
        os.link(partial,target);partial.unlink()
        directory=os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
        with connection.cursor() as cursor:
            cursor.execute('SELECT oid FROM pg_database WHERE datname=%s',(stage,))
            if cursor.fetchone()!=(result['stageOid'],):raise ValueError('The staging identity changed; no database was removed.')
            cursor.execute(sql.SQL('ALTER DATABASE {} WITH ALLOW_CONNECTIONS false').format(sql.Identifier(stage)))
            cursor.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()',(stage,))
            cursor.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(stage)))
        result.update(ok=True,sha256=digest,bytes=target.stat().st_size,restored=counts,stagingDatabaseRemoved=True)
        checkpoint(result,'completed')
    except Exception as error:
        result['failureType']=type(error).__name__
        result['failureLocation']=[{'module':Path(frame.filename).name,'line':frame.lineno} for frame in traceback.extract_tb(error.__traceback__)[-3:]]
        result['error']='Fresh-world preparation failed. The current world was not replaced; retained staging data needs review.'
        checkpoint(result,'failed')
    finally:
        if connection is not None:
            try:
                with connection.cursor() as cursor:cursor.execute('ALTER ROLE dune NOSUPERUSER')
            finally:connection.close()
    return 0 if result['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
