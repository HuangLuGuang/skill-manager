import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError

from backend import models
from backend.access_token_migration import migrate_access_token_ids
from tests.test_backend_index_migrations import startup_twice


def legacy_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE access_tokens (id INTEGER NOT NULL, name TEXT UNIQUE, "
            "issued_by_client_token_id INTEGER, extra TEXT DEFAULT 'preserved', PRIMARY KEY (id))"
        )
        conn.exec_driver_sql("CREATE INDEX credential_name ON access_tokens(name)")
        conn.exec_driver_sql("CREATE TABLE inserted (token_id INTEGER)")
        conn.exec_driver_sql(
            "CREATE TRIGGER credential_insert AFTER INSERT ON access_tokens "
            "BEGIN INSERT INTO inserted VALUES (NEW.id); END"
        )
        conn.exec_driver_sql("INSERT INTO access_tokens(id, name) VALUES (24, 'original')")
        conn.exec_driver_sql("CREATE TABLE runtime_tasks (token_id INTEGER REFERENCES access_tokens(id))")
        conn.exec_driver_sql("INSERT INTO runtime_tasks VALUES (25)")
    return engine


def test_upgrade_preserves_data_schema_and_historical_ids(tmp_path):
    engine = legacy_database(tmp_path)
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    migrate_access_token_ids(engine)
    migrate_access_token_ids(engine)
    with engine.begin() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("SELECT * FROM access_tokens").one() == (24, 'original', None, 'preserved')
        assert conn.exec_driver_sql("SELECT * FROM runtime_tasks").one() == (25,)
        assert conn.exec_driver_sql("PRAGMA foreign_key_list(runtime_tasks)").one()[2] == 'access_tokens'
        assert conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE name='credential_name'").scalar()
        assert conn.exec_driver_sql("INSERT INTO access_tokens(name) VALUES ('new')").lastrowid == 26
        conn.exec_driver_sql("DELETE FROM access_tokens")
    migrate_access_token_ids(engine)
    with engine.begin() as conn:
        assert conn.exec_driver_sql("INSERT INTO access_tokens(name) VALUES ('next')").lastrowid == 27
        assert conn.exec_driver_sql("SELECT max(token_id) FROM inserted").scalar() == 27
        with pytest.raises(IntegrityError, match='UNIQUE constraint failed'):
            conn.exec_driver_sql("INSERT INTO access_tokens(name) VALUES ('next')")
    engine.dispose()


def test_upgrade_failure_rolls_back_table_replacement(tmp_path):
    engine = legacy_database(tmp_path)

    def fail_after_drop(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('ALTER TABLE access_tokens__monotonic_ids'):
            raise RuntimeError('simulated migration failure')

    event.listen(engine, 'before_cursor_execute', fail_after_drop)
    with pytest.raises(RuntimeError, match='simulated'):
        migrate_access_token_ids(engine)
    event.remove(engine, 'before_cursor_execute', fail_after_drop)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT name FROM access_tokens").scalar() == 'original'
        assert conn.exec_driver_sql(
            "SELECT count(*) FROM sqlite_master WHERE name='access_tokens__monotonic_ids'"
        ).scalar() == 0
        assert 'AUTOINCREMENT' not in conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE name='access_tokens'"
        ).scalar()
    migrate_access_token_ids(engine)
    engine.dispose()


def test_empty_legacy_table_recovers_deleted_id_from_audit(tmp_path):
    engine = legacy_database(tmp_path)
    with engine.begin() as conn:
        conn.exec_driver_sql('DELETE FROM access_tokens')
        conn.exec_driver_sql('DELETE FROM runtime_tasks')
        conn.exec_driver_sql('CREATE TABLE security_audit_events (resource_type TEXT, resource_id TEXT)')
        conn.exec_driver_sql(
            "INSERT INTO security_audit_events VALUES ('http_route', '/api/v1/access/tokens/30/revoke')"
        )
    migrate_access_token_ids(engine)
    with engine.begin() as conn:
        assert conn.exec_driver_sql("INSERT INTO access_tokens(name) VALUES ('new')").lastrowid == 31
    engine.dispose()


@pytest.mark.parametrize('legacy', [False, True])
def test_real_startup_and_delete_never_reuse_id(tmp_path, legacy):
    db_path = tmp_path / 'startup.db'
    engine = create_engine(f'sqlite:///{db_path}')
    if legacy:
        from sqlalchemy.schema import CreateTable
        models.Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.exec_driver_sql('DROP TABLE access_tokens')
            ddl = str(CreateTable(models.AccessToken.__table__).compile(engine))
            conn.exec_driver_sql(ddl.replace('AUTOINCREMENT', ''))
            conn.execute(models.AccessToken.__table__.insert().values(
                id=25, name='old', token_type='scanner', token_hash='old', token_prefix='test',
            ))
    startup_twice(tmp_path, db_path)
    with engine.begin() as conn:
        assert 'AUTOINCREMENT' in conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE name='access_tokens'"
        ).scalar()
        token = models.AccessToken.__table__
        values = dict(name='test', token_type='scanner', token_hash='test', token_prefix='test')
        previous = conn.execute(token.insert().values(**values)).inserted_primary_key[0]
        conn.execute(token.delete())
        current = conn.execute(token.insert().values(**values)).inserted_primary_key[0]
        assert current > previous
        if legacy:
            assert previous > 25
    engine.dispose()
