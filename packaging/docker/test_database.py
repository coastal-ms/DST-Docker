"""Integration tests against an isolated PostgreSQL fixture, never a game DB."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import psycopg

spec = importlib.util.spec_from_file_location('database', Path(__file__).with_name('database.py'))
database = importlib.util.module_from_spec(spec)
spec.loader.exec_module(database)


class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='dst-docker-test-')
        cls.root = Path(cls.temp.name)
        cls.config = cls.root / 'database.json'
        cls.secret = cls.root / 'password'
        cls.secret.write_text('')
        cls.settings = {'host': os.environ.get('DST_TEST_POSTGRES_HOST','127.0.0.1'), 'port': int(os.environ.get('DST_TEST_POSTGRES_PORT','18767')), 'database': 'dune', 'user': 'dune',
                        'passwordFile': str(cls.secret), 'allowWrites': True}
        cls.config.write_text(json.dumps(cls.settings))
        with psycopg.connect(host=cls.settings['host'], port=cls.settings['port'], dbname='dune', user='dune', autocommit=True) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS dst_transport_fixture (id integer PRIMARY KEY, value text)')
            connection.execute("INSERT INTO dst_transport_fixture VALUES (1,'original') ON CONFLICT (id) DO UPDATE SET value='original'")

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def run_sql(self, sql, read_only=True, **options):
        return database.execute({'sql': sql, 'readOnly': read_only, **options}, self.config)

    def test_exact_postgres_text_and_csv_values(self):
        result = self.run_sql("SELECT 'Arrakis, \"sand\"'::text AS label, E'line1\\nline2' AS multiline, '生命' AS unicode, NULL AS missing, ''::text AS empty, true AS flag, '{\"x\": 1}'::jsonb AS data")
        self.assertIn('"Arrakis, ""sand"""', result['stdout'])
        self.assertIn('"line1\nline2"', result['stdout'])
        self.assertIn('生命,,"",t,"{""x"": 1}"', result['stdout'])

    def test_read_only_is_enforced_by_postgres(self):
        with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
            self.run_sql("UPDATE dst_transport_fixture SET value='bad' WHERE id=1")
        self.assertIn('original', self.run_sql('SELECT value FROM dst_transport_fixture WHERE id=1')['stdout'])

    def test_cannot_escape_read_transaction_with_multiple_commands(self):
        with self.assertRaises(psycopg.errors.SyntaxError):
            self.run_sql("COMMIT; UPDATE dst_transport_fixture SET value='bad' WHERE id=1")
        self.assertIn('original', self.run_sql('SELECT value FROM dst_transport_fixture WHERE id=1')['stdout'])

    def test_literal_percent_wildcards_and_modulo_preserve_psql_semantics(self):
        result=self.run_sql("SELECT 'TotemOwner' ILIKE '%Totem%' AS matched, 17 % 5 AS remainder, '%s'::text AS literal")
        self.assertIn('t,2,%s',result['stdout'])

    def test_read_only_rejects_local_client_shell_commands(self):
        with self.assertRaises(psycopg.errors.SyntaxError): self.run_sql('\\! touch /tmp/should-never-exist')
        self.assertFalse(Path('/tmp/should-never-exist').exists())

    def test_shared_quiet_directive_is_formatting_only_and_never_changes_sql_literals(self):
        result=self.run_sql("\\set QUIET on\nBEGIN; SELECT 'native'::text AS result; COMMIT;",False,structured=True)
        self.assertEqual(result['resultSet']['rows'],[['native']])
        literal=self.run_sql("SELECT E'\\\\set QUIET on'::text AS value",structured=True)
        self.assertEqual(literal['resultSet']['rows'],[['\\set QUIET on']])
        with self.assertRaises(psycopg.errors.SyntaxError):
            self.run_sql('\\set QUIET on\n\\! touch /tmp/should-never-exist',False)
        self.assertFalse(Path('/tmp/should-never-exist').exists())

    def test_multi_statement_transaction_and_row_tags_remain_compatible(self):
        result = self.run_sql("BEGIN; UPDATE dst_transport_fixture SET value='changed' WHERE id=1; ROLLBACK;", False)
        self.assertIn('UPDATE 1', result['stdout'])
        self.assertIn('original', self.run_sql('SELECT value FROM dst_transport_fixture WHERE id=1')['stdout'])

    def test_structured_transaction_keeps_final_table_separate_from_command_tags(self):
        result=self.run_sql("BEGIN; SET LOCAL lock_timeout='1s'; CREATE TEMP TABLE dst_result_probe(value integer); DO $$ BEGIN NULL; END $$; SELECT 1 AS changed, 'DO'::text AS label, NULL::text AS missing, ''::text AS empty; COMMIT;",False,structured=True)
        table=result['resultSet']
        self.assertEqual(table['columns'],['changed','label','missing','empty'])
        self.assertEqual(table['rows'],[['1','DO',None,'']])
        self.assertEqual(table['rowCount'],1)

    def test_structured_results_bound_rows_and_preserve_command_only_affected_count(self):
        table=self.run_sql('SELECT generate_series(1,3) AS value',structured=True,maxRows=1)['resultSet']
        self.assertEqual(table['rows'],[['1']]);self.assertTrue(table['truncated'])
        command=self.run_sql('UPDATE dst_transport_fixture SET value=value WHERE id=1',False,structured=True)['resultSet']
        self.assertEqual(command['message'],'UPDATE 1');self.assertEqual(command['rows'],[])

    def test_large_query_is_not_limited_by_command_line(self):
        result = self.run_sql('SELECT length(' + "'" + ('x' * 300000) + "') AS count")
        self.assertIn('300000', result['stdout'])

    def test_write_permission_must_be_explicit_in_protected_settings(self):
        settings = dict(self.settings, allowWrites=False)
        config = self.root / 'read-only.json'
        config.write_text(json.dumps(settings))
        with self.assertRaises(ValueError):
            database.execute({'sql': 'SELECT 1', 'readOnly': False}, config)

    def test_restore_maintenance_blocks_inflight_workflow_followup_queries(self):
        marker=self.root/'docker-maintenance.json'
        try:
            marker.write_text(json.dumps({'active':True}))
            with self.assertRaisesRegex(ValueError,'restore is in progress'):
                self.run_sql("UPDATE dst_transport_fixture SET value='bad' WHERE id=1",False)
            marker.write_text('broken')
            with self.assertRaisesRegex(ValueError,'maintenance status'):
                self.run_sql('SELECT 1')
        finally:marker.unlink(missing_ok=True)
        self.assertIn('original',self.run_sql('SELECT value FROM dst_transport_fixture WHERE id=1')['stdout'])

    def test_secret_path_cannot_escape_protected_settings_directory(self):
        settings = dict(self.settings, passwordFile='/etc/passwd')
        config = self.root / 'bad-path.json'
        config.write_text(json.dumps(settings))
        with self.assertRaises(ValueError): database.load_config(config)

    def test_server_statement_timeout(self):
        with self.assertRaises(psycopg.errors.QueryCanceled):
            self.run_sql('SELECT pg_sleep(3)', timeoutSeconds=1)

    def test_no_csv_retains_unaligned_scalar_output(self):
        self.assertEqual(self.run_sql('SELECT 42', csv=False)['stdout'], '42\n')


if __name__ == '__main__': unittest.main()
