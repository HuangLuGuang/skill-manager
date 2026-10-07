"""Legacy P1 evidence must survive the device-only schema upgrade."""
import pytest
import json
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from backend import models
from backend.sqlite_db import Base
from backend.aidr_migrations import upgrade_aidr_schema
from backend.aidr_models import AidrHookEvent, AidrOperation
from backend.aidr_enforcement import AidrRuntimeRecord
from backend.runtime_governance import Observation, view


def legacy_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine)
    tables = [models.AidrDevice, models.AidrBatch, models.AidrEvent, models.AidrSource, models.AidrCoverageRecord]
    with engine.begin() as c:
        c.exec_driver_sql('DROP INDEX ix_aidr_session_messages')
        for model in (models.AidrEvent, models.AidrCoverageRecord):
            c.exec_driver_sql(f'DROP INDEX ix_{model.__tablename__}_retention')
            c.exec_driver_sql(f'ALTER TABLE {model.__tablename__} DROP COLUMN expired_at')
        # Actual legacy columns were required; the suffix is archived from these rows.
        for model in tables:
            c.exec_driver_sql(f'ALTER TABLE {model.__tablename__} ADD COLUMN group_id INTEGER NOT NULL DEFAULT 17')
        c.execute(models.ManagedClient.__table__.insert().values(client_id="old",name="old",hostname="host",os="darwin",arch="arm64",client_version="test",registered_by="owner"))
        c.exec_driver_sql("INSERT INTO aidr_devices VALUES('old',0,NULL,'{}','[]','owner','2026-09-23',17)")
        c.exec_driver_sql("INSERT INTO aidr_batches VALUES(7,'old','stream','batch','digest',2,'2026-09-23',17)")
        vectors=json.loads((Path(__file__).parents[1]/'scanner/internal/aidr/agentlog/testdata/contracts.json').read_text())
        payload=json.dumps(next(v['event'] for v in vectors if v['valid']))
        c.exec_driver_sql("INSERT INTO aidr_events VALUES(9,'old','logical','hash','claude','tool_call',?,'2026-09-23',17)",(payload,))
        c.exec_driver_sql("INSERT INTO aidr_sources VALUES(11,'old','stream','source',4,'{\"cursor\":\"raw\"}','2026-09-23',17)")
        c.exec_driver_sql("INSERT INTO aidr_coverage_records VALUES(12,'old','stream','source:4','{}','hash','2026-09-23',17)")
    return engine, tables


def test_upgrade_preserves_all_evidence_and_is_repeatable(tmp_path):
    engine, tables = legacy_database(tmp_path)
    with engine.connect() as c:
        before = {m.__tablename__: [dict(r) for r in c.exec_driver_sql(f'SELECT * FROM {m.__tablename__}').mappings()] for m in tables}
    upgrade_aidr_schema(engine)
    upgrade_aidr_schema(engine)
    with engine.connect() as c:
        for name, rows in before.items():
            keys = set(rows[0]) - {'group_id'}
            assert [{k:v for k,v in r.items() if k in keys} for r in c.exec_driver_sql(f'SELECT * FROM {name}').mappings()] == [{k:v for k,v in r.items() if k != 'group_id'} for r in rows]
        assert c.exec_driver_sql("SELECT client_id,suffix FROM aidr_legacy_destinations").all() == [('old','17')]
        assert not c.exec_driver_sql('PRAGMA foreign_key_check(aidr_events)').all()
        plan = c.exec_driver_sql("EXPLAIN QUERY PLAN SELECT agent,payload_json FROM aidr_events WHERE client_id='old' AND id<=100 AND expired_at IS NULL AND kind IN ('user_message','assistant_message')").all()
        assert any('ix_aidr_session_messages' in row[3] for row in plan)
        assert c.exec_driver_sql('SELECT count(*) FROM aidr_operations').scalar() == 1
        view=json.loads(c.exec_driver_sql('SELECT payload_json FROM aidr_operations').scalar())
        assert view['call']['schema_version']==1 and not view['call'].get('behavior')
        assert c.exec_driver_sql("SELECT value FROM aidr_audit_state WHERE key='event_watermark'").scalar()==9
    engine.dispose()


def test_runtime_policy_upgrade_preserves_existing_tasks_and_default(tmp_path):
    engine, tables = legacy_database(tmp_path)
    with engine.begin() as c:
        c.exec_driver_sql('ALTER TABLE client_governance_policies DROP COLUMN runtime_governance_json')
        c.exec_driver_sql("INSERT INTO client_governance_policies(scope,rules_json,prompt_guard_json,compression_json,model_routing_json,revision,enabled,protocol,updated_at) VALUES('@default','{}','null','null','null',4,1,2,'2026-09-30 00:00:00')")
        c.execute(models.ClientTask.__table__.insert().values(client_id='old',task_type='aidr_plugin_action',payload_json='{"frozen":"exact-old-task"}',request_key='old-runtime-task'))
        before = list(c.exec_driver_sql('SELECT * FROM client_tasks').all())
        batches = list(c.exec_driver_sql('SELECT batch_id,digest FROM aidr_batches').all())
    upgrade_aidr_schema(engine)
    upgrade_aidr_schema(engine)
    with engine.connect() as c:
        assert c.exec_driver_sql("SELECT revision,runtime_governance_json FROM client_governance_policies WHERE scope='@default'").one() == (4,'null')
        assert list(c.exec_driver_sql('SELECT * FROM client_tasks').all()) == before
        assert list(c.exec_driver_sql('SELECT batch_id,digest FROM aidr_batches').all()) == batches
    engine.dispose()


def test_failed_upgrade_rolls_back_all_tables(tmp_path):
    engine, tables = legacy_database(tmp_path)
    with engine.begin() as c:
        c.exec_driver_sql("UPDATE aidr_sources SET client_id='missing'")
    with pytest.raises(RuntimeError, match='aidr_migration_reference_invalid'):
        upgrade_aidr_schema(engine)
    with engine.connect() as c:
        for model in tables:
            assert 'group_id' in {r[1] for r in c.exec_driver_sql(f'PRAGMA table_info({model.__tablename__})')}
        assert c.exec_driver_sql('SELECT count(*) FROM aidr_legacy_destinations').scalar() == 0
    engine.dispose()


def test_lifecycle_upgrade_adds_metadata_without_expiring_or_rewriting_evidence(tmp_path):
    engine, _ = legacy_database(tmp_path)
    with engine.begin() as c:
        for model in (AidrHookEvent, AidrOperation, AidrRuntimeRecord):
            c.exec_driver_sql(f'DROP INDEX ix_{model.__tablename__}_retention')
            c.exec_driver_sql(f'ALTER TABLE {model.__tablename__} DROP COLUMN expired_at')
        c.exec_driver_sql('ALTER TABLE aidr_operations DROP COLUMN received_at')
        c.exec_driver_sql('ALTER TABLE aidr_runtime_records DROP COLUMN content_hash')
        c.exec_driver_sql('ALTER TABLE aidr_policy_receipts DROP COLUMN lifecycle_json')
        before = c.exec_driver_sql('SELECT logical_id,content_hash,payload_json FROM aidr_events').all()
        batches = c.exec_driver_sql('SELECT batch_id,digest FROM aidr_batches').all()
    upgrade_aidr_schema(engine)
    upgrade_aidr_schema(engine)
    with engine.connect() as c:
        assert c.exec_driver_sql('SELECT logical_id,content_hash,payload_json FROM aidr_events').all() == before
        assert c.exec_driver_sql('SELECT batch_id,digest FROM aidr_batches').all() == batches
        assert c.exec_driver_sql('SELECT expired_at FROM aidr_events').scalar() is None
        assert c.exec_driver_sql('SELECT received_at FROM aidr_operations').scalar() is not None
        assert 'lifecycle_json' in {r[1] for r in c.exec_driver_sql('PRAGMA table_info(aidr_policy_receipts)')}
        assert 'content_hash' in {r[1] for r in c.exec_driver_sql('PRAGMA table_info(aidr_runtime_records)')}
    engine.dispose()


def runtime_database(tmp_path,legacy=True):
    engine=create_engine(f"sqlite:///{tmp_path / 'runtime.db'}")
    Base.metadata.create_all(engine)
    cases={"zero":{"protocol":0},"one":{"protocol":1},"two":{"protocol":2},"missing":{},"string":{"protocol":"1"},"invalid":{"protocol":1,"unexpected":True}}
    with engine.begin() as c:
        if legacy: c.exec_driver_sql("ALTER TABLE client_runtime_governance DROP COLUMN supports_tasks")
        for key,fields in cases.items():
            c.execute(models.ManagedClient.__table__.insert().values(client_id=key,name=key,hostname="test",os="darwin",arch="arm64",client_version="test",registered_by="owner"))
            raw=json.dumps(dict(plugin_version="test",receiver_code="aidr_receiver_stopped",hosts=[],**fields))
            if legacy:
                c.exec_driver_sql("INSERT INTO client_runtime_governance(client_id,report_json,reported_at) VALUES(?,?,'2026-10-02 00:00:00')",(key,raw))
            else:
                from datetime import datetime
                c.execute(Observation.__table__.insert().values(client_id=key, report_json=raw, reported_at=datetime(2026,10,2)))
        c.execute(models.ClientTask.__table__.insert().values(client_id='one',task_type='aidr_plugin_action',payload_json='{"frozen":"unchanged"}',request_key='preserve'))
    return engine

def test_runtime_upgrade_protocol_and_evidence(tmp_path):
    e=runtime_database(tmp_path)
    with e.connect() as c:
        before=c.exec_driver_sql("SELECT client_id,report_json,reported_at FROM client_runtime_governance ORDER BY client_id").all()
        tasks=c.exec_driver_sql("SELECT * FROM client_tasks").all()
    upgrade_aidr_schema(e);upgrade_aidr_schema(e)
    with e.connect() as c:
        assert c.exec_driver_sql("SELECT client_id,report_json,reported_at FROM client_runtime_governance ORDER BY client_id").all()==before
        assert c.exec_driver_sql("SELECT * FROM client_tasks").all()==tasks
        assert dict(c.exec_driver_sql("SELECT client_id,supports_tasks FROM client_runtime_governance").all())==dict(zero=0,one=1,two=1,missing=0,string=0,invalid=0)
    with Session(e) as s:
        assert view(s,'one')['supports_tasks'] is True
        assert view(s,'zero')['supports_tasks'] is False
    e.dispose()

def test_runtime_upgrade_interruption_rolls_back_and_recovers(tmp_path):
    e=runtime_database(tmp_path)
    def fail(c,cursor,statement,parameters,context,many):
        if statement.startswith('UPDATE client_runtime_governance'): raise RuntimeError('injected_interruption')
    event.listen(e,'before_cursor_execute',fail)
    with pytest.raises(RuntimeError,match='injected_interruption'): upgrade_aidr_schema(e)
    event.remove(e,'before_cursor_execute',fail)
    with e.connect() as c:
        assert 'supports_tasks' not in {r[1] for r in c.exec_driver_sql('PRAGMA table_info(client_runtime_governance)')}
        assert c.exec_driver_sql('SELECT count(*) FROM client_runtime_governance').scalar()==6
    upgrade_aidr_schema(e)
    with e.connect() as c: assert c.exec_driver_sql("SELECT supports_tasks FROM client_runtime_governance WHERE client_id='two'").scalar()==1
    e.dispose()

def test_new_runtime_database_is_unchanged(tmp_path):
    e=runtime_database(tmp_path,legacy=False)
    with e.connect() as c: before=c.exec_driver_sql('SELECT * FROM client_runtime_governance ORDER BY client_id').all()
    upgrade_aidr_schema(e);upgrade_aidr_schema(e)
    with e.connect() as c: assert c.exec_driver_sql('SELECT * FROM client_runtime_governance ORDER BY client_id').all()==before
    e.dispose()
