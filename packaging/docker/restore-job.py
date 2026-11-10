"""Restore an owned snapshot through a verified stage and reversible DB rename.

Never drops the previous database. Fault injection is restricted by the typed
manager factory to generated qualification databases, not the live world.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

REPORT=Path('/tmp/dst-result.json')


def checkpoint(result,phase):
    result['phase']=phase;result['updatedAt']=time.time()
    temporary=REPORT.with_suffix('.tmp');temporary.write_text(json.dumps(result));temporary.replace(REPORT)


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def run(*command,capture=False):
    result=subprocess.run(command,check=False,stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL,timeout=1800)
    if result.returncode:raise RuntimeError('PostgreSQL restore operation failed. Recovery data was preserved.')
    return result.stdout.decode('utf-8').strip() if capture else ''


def sql(database,statement):
    return run('psql','-X','-t','-A','-d',database,'-v','ON_ERROR_STOP=1','-c',statement,capture=True)


def oid(name):
    value=sql('postgres',"SELECT oid FROM pg_database WHERE datname='"+name+"'")
    return int(value) if value else None


def counts(name):
    return json.loads(sql(name,"SELECT json_build_object('duneTables',(SELECT count(*) FROM information_schema.tables WHERE table_schema='dune' AND table_type='BASE TABLE'),'duneViews',(SELECT count(*) FROM information_schema.views WHERE table_schema='dune'),'partitions',(SELECT count(*) FROM dune.world_partition),'players',(SELECT count(*) FROM dune.player_state))"))


def fence(*names):
    for name in names:sql('postgres','ALTER DATABASE '+name+' WITH ALLOW_CONNECTIONS false')
    literals=','.join("'"+name+"'" for name in names)
    sql('postgres','SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('+literals+') AND pid<>pg_backend_pid()')


def permit(name):sql('postgres','ALTER DATABASE '+name+' WITH ALLOW_CONNECTIONS true')


def rollback(result):
    target=result['target'];previous=result['previousDatabase'];failed=result['failedDatabase']
    original_oid=result['originalOid'];stage_oid=result.get('stageOid')
    if oid(target)==original_oid:
        if result.get('connectionsFenced'):permit(target)
        result['originalPreserved']=True;return
    if oid(previous)!=original_oid or oid(target)!=stage_oid or oid(failed) is not None:
        raise RuntimeError('Database identities need recovery review; no additional rename was performed.')
    checkpoint(result,'rolling-back')
    fence(target,previous)
    sql('postgres','BEGIN; ALTER DATABASE '+target+' RENAME TO '+failed+'; ALTER DATABASE '+previous+' RENAME TO '+target+'; COMMIT;')
    permit(target)
    if oid(target)!=original_oid:raise RuntimeError('Recovery identity verification failed.')
    result.update(rollbackPerformed=True,originalPreserved=True)


def main():
    os.umask(0o077)
    result={'ok':False,'startedAt':time.time(),'rollbackPerformed':False,'originalPreserved':True}
    try:
        project=os.environ['DST_PROJECT_ID'];operation=os.environ['DST_OPERATION_ID']
        target=os.environ['DST_TARGET_DATABASE'];name=os.environ['DST_BACKUP_NAME']
        before=os.environ['DST_BEFORE_BACKUP_NAME'];expected=os.environ['DST_EXPECTED_SHA256']
        qualification=os.environ.get('DST_QUALIFICATION')=='1'
        fault=os.environ.get('DST_RESTORE_FAULT','')
        mode=os.environ.get('DST_RESTORE_MODE','restore')
        if not re.fullmatch(r'[a-f0-9]{32}',project) or not re.fullmatch(r'[a-f0-9]{32}',operation):raise ValueError('Invalid owned restore identity.')
        if not (target=='dune' and not qualification or qualification and re.fullmatch(r'dst_qualify_[a-f0-9]{24}',target)):
            raise ValueError('Invalid restore database scope.')
        if mode not in {'restore','recover'} or fault not in {'','before-promotion','after-promotion','kill-after-promotion'} or fault and not qualification:
            raise ValueError('Invalid internal restore mode.')
        if not all(re.fullmatch(r'backup-[0-9]+-[a-f0-9]{8}\.dump',value) for value in [name,before]):raise ValueError('Invalid owned backup name.')
        if not re.fullmatch(r'[a-f0-9]{64}',expected):raise ValueError('Invalid backup checksum.')
        host=os.environ['DST_DATABASE_HOST']
        if host!='dst-'+project+'-postgres':raise ValueError('Restore database is outside this installation.')
        os.environ.update(PGHOST=host,PGPORT='5432',PGUSER='postgres',PGCONNECT_TIMEOUT='10',
                          PGPASSWORD=Path('/run/dst/postgres-admin.password').read_text())
        suffix=operation[:24]
        stage='dst_restore_'+suffix;previous='dst_previous_'+suffix;failed='dst_failed_'+suffix
        result.update(operationId=operation,target=target,name=name,stagingDatabase=stage,
                      previousDatabase=previous,failedDatabase=failed)
        if mode=='recover':
            result['originalOid']=int(os.environ['DST_ORIGINAL_OID']);result['stageOid']=int(os.environ['DST_STAGE_OID'])
            result['connectionsFenced']=os.environ.get('DST_CONNECTIONS_FENCED')=='1'
            if result['originalOid']<=0 or result['stageOid']<=0:raise ValueError('Invalid recovery identities.')
            rollback(result);result['ok']=True;checkpoint(result,'recovered');return 0
        source=Path('/backups')/name
        if digest(source)!=expected:raise ValueError('The selected backup checksum does not match its saved record.')
        if any(oid(database) is not None for database in [stage,previous,failed]):raise ValueError('This restore operation already has recovery data; review it before retrying.')
        result['originalOid']=oid(target)
        if result['originalOid'] is None:raise ValueError('The current database is unavailable.')
        checkpoint(result,'protecting-current-database')
        recovery=Path('/backups')/before;partial=recovery.with_suffix('.partial')
        with partial.open('xb'):pass
        run('pg_dump','-Fc','-d',target,'-f',str(partial));run('pg_restore','--list',str(partial));partial.replace(recovery)
        result['beforeBackup']={'name':before,'sha256':digest(recovery),'bytes':recovery.stat().st_size}
        checkpoint(result,'restoring-stage')
        run('createdb','-O','dune',stage);result['stageOid']=oid(stage);checkpoint(result,'restoring-stage')
        run('pg_restore','--exit-on-error','-d',stage,str(source))
        restored=counts(stage);expected_counts=json.loads(os.environ['DST_EXPECTED_COUNTS'])
        if restored!=expected_counts:raise ValueError('The staged restore does not match the verified backup record.')
        accessible=int(sql(stage,'SET ROLE dune; SELECT count(*) FROM dune.player_state').splitlines()[-1])
        if accessible!=restored['players']:raise ValueError('The application role could not verify the staged character data.')
        if sql('postgres',"SELECT rolsuper FROM pg_roles WHERE rolname='dune'")!='f':raise ValueError('The application role has unexpected privileges.')
        if digest(source)!=expected:raise ValueError('The selected backup changed during restore verification.')
        result['restored']=restored;checkpoint(result,'stage-verified')
        if fault=='before-promotion':raise RuntimeError('Injected qualification failure before promotion.')
        result['connectionsFenced']=True;checkpoint(result,'fencing-connections')
        fence(target,stage);checkpoint(result,'promoting')
        sql('postgres','BEGIN; ALTER DATABASE '+target+' RENAME TO '+previous+'; ALTER DATABASE '+stage+' RENAME TO '+target+'; COMMIT;')
        # Namespace PID 1 has special signal handling. _exit simulates an
        # abrupt process loss reliably, bypassing exception/finally cleanup.
        if fault=='kill-after-promotion':os._exit(137)
        checkpoint(result,'promoted')
        if fault=='after-promotion':raise RuntimeError('Injected qualification failure after promotion.')
        permit(target)
        if oid(target)!=result['stageOid'] or oid(previous)!=result['originalOid'] or counts(target)!=restored:
            raise RuntimeError('Promoted database verification failed.')
        result.update(ok=True,originalPreserved=True);checkpoint(result,'completed')
    except (ValueError,RuntimeError) as error:
        result['error']=str(error)
        if result.get('originalOid'):
            try:rollback(result)
            except Exception:result.update(recoveryRequired=True,originalPreserved=False)
        checkpoint(result,'failed')
    except Exception:
        result['error']='Restore interrupted. Database and backup recovery data were preserved.'
        if result.get('originalOid'):
            try:rollback(result)
            except Exception:result.update(recoveryRequired=True,originalPreserved=False)
        checkpoint(result,'failed')
    return 0 if result['ok'] else 1


if __name__=='__main__':sys.exit(main())
