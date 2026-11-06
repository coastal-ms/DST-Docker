"""DST SQL transport over PostgreSQL; request/response JSON on stdio only."""
import json
import re
from pathlib import Path
import sys

CONFIG = Path('/data/config/DuneServer/docker-database.json')
MAX_BYTES = 32 * 1024 * 1024


def load_config(path=CONFIG):
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    allowed = {'host', 'port', 'database', 'user', 'passwordFile', 'allowWrites'}
    if set(config) - allowed:
        raise ValueError('Unsupported database configuration fields.')
    for key in ['host', 'database', 'user']:
        if not isinstance(config.get(key), str) or not config[key] or len(config[key]) > 255:
            raise ValueError('Database connection settings are incomplete.')
    port = config.get('port', 5432)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid database port.')
    secret = Path(config.get('passwordFile', '/data/config/DuneServer/docker-db.password'))
    if not secret.resolve().is_relative_to(path.parent.resolve()):
        raise ValueError('Database password must be inside the protected configuration directory.')
    return config, secret.read_text(encoding='utf-8').rstrip('\r\n')


def render_result(result, csv_mode):
    if result.nfields:
        columns = [result.fname(col).decode('utf-8') for col in range(result.nfields)]
        rows = [[None if result.get_value(row, col) is None else result.get_value(row, col).decode('utf-8')
                 for col in range(result.nfields)] for row in range(result.ntuples)]
        if csv_mode:
            # PostgreSQL CSV distinguishes NULL (unquoted empty) from an empty
            # string (quoted empty). Preserve the wire values and that distinction.
            def field(value):
                if value is None: return ''
                if value == '' or any(char in value for char in ',"\r\n'):
                    return '"' + value.replace('"', '""') + '"'
                return value
            return '\n'.join(','.join(field(v) for v in row) for row in [columns, *rows]) + '\n'
        return '\n'.join('|'.join('' if value is None else value for value in row) for row in rows) + ('\n' if rows else '')
    return (result.command_status or b'').decode('utf-8') + '\n'


def execute(request, config_path=CONFIG):
    import psycopg
    config, password = load_config(config_path)
    maintenance=Path(config_path).parent/'docker-maintenance.json'
    if maintenance.exists():
        try:active=json.loads(maintenance.read_text()).get('active')
        except (ValueError,OSError,AttributeError):raise ValueError('Database maintenance status could not be read.') from None
        if active:raise ValueError('Database restore is in progress.')
    sql = request.get('sql')
    if not isinstance(sql, str) or not sql.strip() or len(sql.encode('utf-8')) > MAX_BYTES:
        raise ValueError('SQL is empty or exceeds the request limit.')
    # Shared reviewed-grant scripts ask psql to suppress command tags. The
    # native driver already separates those tags; discard only that leading
    # formatting directive. Never interpret client commands or SQL body text.
    sql=re.sub(r'^\s*\\set[ \t]+QUIET[ \t]+on[ \t]*(?:\r?\n|$)','',sql,count=1,flags=re.IGNORECASE)
    read_only = request.get('readOnly', True) is not False
    if not read_only and config.get('allowWrites') is not True:
        raise ValueError('Database writes have not been enabled for this Docker server.')
    timeout = max(1, min(600, int(request.get('timeoutSeconds', 30))))
    output = []
    size = 0
    structured=request.get('structured') is True
    max_rows=max(1,int(request.get('maxRows',1000)))
    table=None;command=''
    with psycopg.connect(host=config['host'], port=config.get('port', 5432),
                         dbname=config['database'], user=config['user'], password=password,
                         connect_timeout=min(timeout, 8), application_name='DST Docker',
                         options=f'-c statement_timeout={timeout * 1000} -c lock_timeout=5000',
                         autocommit=not read_only) as connection:
        if read_only:
            connection.read_only = True
        with connection.cursor() as cursor:
            # A read uses one extended-protocol statement. A caller cannot
            # escape the read-only transaction with "COMMIT; UPDATE ...".
            # No bind parameters: this is existing complete PostgreSQL text,
            # whose LIKE patterns and modulo operators must retain literal %.
            # prepare=True still forces one extended-protocol statement.
            cursor.execute(sql, None, prepare=True if read_only else False)
            while True:
                result = cursor.pgresult
                if result:
                    if structured:
                        if result.nfields:
                            table={'columns':[result.fname(col).decode('utf-8') for col in range(result.nfields)],
                                   'rows':[[None if result.get_value(row,col) is None else result.get_value(row,col).decode('utf-8')
                                            for col in range(result.nfields)] for row in range(min(max_rows,result.ntuples))],
                                   'rowCount':min(max_rows,result.ntuples),'truncated':result.ntuples>max_rows,'message':''}
                            if len(json.dumps(table,ensure_ascii=False).encode())>MAX_BYTES:raise ValueError('Database response exceeds the transport limit.')
                        else:
                            tag=(result.command_status or b'').decode('utf-8')
                            if tag.split(' ',1)[0] not in {'BEGIN','COMMIT','ROLLBACK','SET','SAVEPOINT','RELEASE'}:command=tag
                        rendered=''
                    else:rendered = render_result(result, bool(request.get('csv', True)))
                    size += len(rendered.encode('utf-8'))
                    if size > MAX_BYTES:
                        raise ValueError('Database response exceeds the transport limit.')
                    output.append(rendered)
                if not cursor.nextset(): break
        if read_only: connection.rollback()
    response={'exitCode': 0, 'stdout': ''.join(output), 'stderr': ''}
    if structured:response['resultSet']=table if table is not None else {'columns':[],'rows':[],'rowCount':0,'truncated':False,'message':command}
    return response


def main():
    try:
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES: raise ValueError('Database request exceeds the transport limit.')
        result = execute(json.loads(data.decode('utf-8-sig')))
    except FileNotFoundError:
        result = {'exitCode': 1, 'stdout': '', 'stderr': 'Docker database connection has not been configured.'}
    except Exception as error:
        # Do not return connection strings or credentials from driver failures.
        sqlstate = getattr(error, 'sqlstate', None)
        if sqlstate:
            message = 'ERROR: ' + (getattr(error.diag, 'message_primary', '') or 'Database statement failed.')
        elif isinstance(error, ValueError): message = 'ERROR: ' + str(error)
        else: message = 'ERROR: Docker database connection failed. Check connection settings and server readiness.'
        result = {'exitCode': 1, 'stdout': '', 'stderr': message}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
