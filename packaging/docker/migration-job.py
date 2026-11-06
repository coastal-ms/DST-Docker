"""Run official migrations on DST's isolated database, with verified backup."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time
import psycopg2

host=os.environ['DST_DATABASE_HOST']
backup=Path('/backups')/os.environ['DST_BACKUP_NAME']
admin_password=Path('/run/dst/postgres-admin.password').read_text()
app_password=Path('/run/dst/dune-app.password').read_text()
connection=psycopg2.connect(host=host,port=5432,dbname='postgres',user='postgres',password=admin_password)
connection.autocommit=True
exit_code=1
elevated=False
backup_verified=False
try:
    # This job has no browser-supplied executable, SQL, path or database host.
    subprocess.run(['/usr/bin/pg_dump','-h',host,'-U','dune','-d','dune','-F','c','--no-owner','--file',str(backup)],
                   env={**os.environ,'PGPASSWORD':app_password},check=True)
    subprocess.run(['/usr/bin/pg_restore','--list',str(backup)],stdout=subprocess.DEVNULL,check=True)
    with backup.open('rb') as source: digest=hashlib.file_digest(source,'sha256').hexdigest()
    backup_verified=True
    with connection.cursor() as cursor: cursor.execute('ALTER ROLE dune SUPERUSER')
    elevated=True
    sys.argv=['updatedb.py','--host',host+':5432','--project-database','dune','--project-user','dune',
              '--project-password',app_password,'--admin-user','postgres','--admin-password',admin_password,
              '--admin-database','postgres','--postgres-installation','/usr','--unattended','--no-backup']
    sys.path.insert(0,'/root/PSQL')
    # The tool's second dump is omitted only after our persistent dump and
    # archive validation both succeeded. Backup failures stop before elevation.
    try:
        runpy.run_path('/root/PSQL/updatedb.py',run_name='__main__')
        exit_code=0
    except SystemExit as result: exit_code=int(result.code or 0)
finally:
    try:
        with connection.cursor() as cursor: cursor.execute('ALTER ROLE dune NOSUPERUSER')
        elevated=False
    finally:
        connection.close()
        report={'exitCode':exit_code,'backupVerified':backup_verified,'backup':backup.name,
                'sha256':digest if backup_verified else None,'roleElevated':elevated,'finishedAt':time.time(),
                'operationId':os.environ.get('DST_OPERATION_ID')}
        backup.with_suffix('.result.json').write_text(json.dumps(report),encoding='utf-8')
        Path('/tmp/dst-result.json').write_text(json.dumps(report),encoding='utf-8')
sys.exit(exit_code)
