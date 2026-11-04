"""Exercise legacy index repair through the real backend startup migrations."""
import os
from datetime import datetime
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect

from backend import models


INDEXES = (
    (models.AccessToken, "bound_client_id", "ix_access_tokens_bound_client_id"),
    (models.ManagedAgent, "created_by", "ix_managed_agents_created_by"),
    (models.SecurityScanTask, "continued_from_task_id", "ix_security_scan_tasks_continued_from_task_id"),
)


def test_startup_adds_mcp_audit_name_without_rewriting_history(tmp_path):
    db_path = tmp_path / "mcp-upgrade.db"
    engine = create_engine(f"sqlite:///{db_path}")
    models.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE mcp_call_audits DROP COLUMN token_name")
        conn.exec_driver_sql("DROP INDEX ix_mcp_call_audits_created_id")
        conn.exec_driver_sql("DROP INDEX ix_mcp_call_audits_duration_id")
        conn.exec_driver_sql(
            "INSERT INTO mcp_call_audits (request_id, token_id, gateway_slug, status, duration_ms, created_at) "
            "VALUES ('historical-call', 25, 'example', 'success', 1, CURRENT_TIMESTAMP)"
        )
    startup_twice(tmp_path, db_path)
    with engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT token_id, token_name FROM mcp_call_audits").one()
        assert row == (25, None)
        indexes = {item['name'] for item in inspect(conn).get_indexes('mcp_call_audits')}
        assert {'ix_mcp_call_audits_created_id', 'ix_mcp_call_audits_duration_id'} <= indexes
    engine.dispose()


def test_startup_upgrades_runtime_action_estimates(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'runtime-upgrade.db'}")
    models.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(models.RuntimeAction.__table__.insert().values(
            action_id="historical", task_id="task", stage="execute", action_type="http",
            target="example.com", risk_level="low", plan_step="send", parameters_hash="digest",
            decision="allow", status="succeeded",
        ))
        for column in ("estimated_cost_microunits", "estimated_data_bytes"):
            conn.exec_driver_sql(f"ALTER TABLE runtime_actions DROP COLUMN {column}")
    startup_twice(tmp_path, tmp_path / 'runtime-upgrade.db')
    with engine.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT action_id, status, estimated_cost_microunits, estimated_data_bytes FROM runtime_actions"
        ).one()
        assert row == ("historical", "succeeded", 0, 0)
    engine.dispose()


def seed_records(engine, prefix):
    with engine.begin() as conn:
        for number, value in enumerate(("shared-value", "shared-value", None)):
            identity = f"{prefix}-{number}"
            conn.execute(models.AccessToken.__table__.insert().values(
                name=identity, token_type="scanner", token_hash=f"test-hash-{identity}",
                token_prefix="test", bound_client_id=value, status="disabled",
            ))
            conn.execute(models.ManagedAgent.__table__.insert().values(
                agent_id=identity, name=identity, created_by=value,
            ))
            conn.execute(models.SecurityScanTask.__table__.insert().values(
                task_id=identity, target_id="target", policy_id="policy", created_by="admin",
                idempotency_key=identity, request_fingerprint=identity,
                timeout_at=datetime(2030, 1, 1), continued_from_task_id=value,
            ))


def startup_twice(tmp_path, db_path):
    # Keep startup's database, signing files and generated data in the test directory.
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
           "SQLITE_PATH": str(db_path), "DATA_DIR": str(tmp_path / "data"),
           "UPLOADS_DIR": str(tmp_path / "uploads"), "AGENT_MANAGER_DATA_DIR": str(tmp_path / "registry"),
           "AGENT_MANAGER_REGISTRY_SQLITE_PATH": str(db_path),
           "AUDIT_SIGNING_PRIVATE_KEY_PATH": str(tmp_path / "audit.pem"),
           "SECURITY_AUDIT_EXPORT_PATH": "", "AGENT_SECURITY_WORKER_TOKEN": "",
           "ENFORCE_SECURE_STARTUP": "false"}
    result = subprocess.run(
        [sys.executable, "-c", """
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
import agent_manager.api.router as native
native._discover_policy_path = lambda: None
import backend.main as main
main.ensure_sqlite_schema()
"""], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("stage", ["fresh", "missing_indexes", "missing_columns"])
def test_startup_repairs_legacy_indexes_and_preserves_records(tmp_path, stage):
    db_path = tmp_path / "upgrade.db"
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        before = {}
        if stage != "fresh":
            models.Base.metadata.create_all(engine)
            seed_records(engine, "before")
            with engine.begin() as conn:
                for model, column, index in INDEXES:
                    table = model.__tablename__
                    conn.exec_driver_sql(f'DROP INDEX "{index}"')
                    if stage == "missing_columns":
                        conn.exec_driver_sql(f'ALTER TABLE "{table}" DROP COLUMN "{column}"')
                    before[table] = [dict(row) for row in conn.exec_driver_sql(
                        f'SELECT * FROM "{table}" ORDER BY id'
                    ).mappings()]

        startup_twice(tmp_path, db_path)

        with engine.connect() as conn:
            for model, column, index in INDEXES:
                table = model.__tablename__
                actual = [i for i in inspect(conn).get_indexes(table) if i["name"] == index]
                assert len(actual) == 1
                assert actual[0]["column_names"] == [column]
                assert not actual[0]["unique"]
                rows = [dict(row) for row in conn.exec_driver_sql(f'SELECT * FROM "{table}" ORDER BY id').mappings()]
                if stage != "fresh":
                    old_columns = before[table][0].keys()
                    assert [{key: row[key] for key in old_columns} for row in rows] == before[table]
                    if stage == "missing_columns":
                        assert all(row[column] is None for row in rows)
                plan = conn.exec_driver_sql(
                    f'EXPLAIN QUERY PLAN SELECT id FROM "{table}" WHERE "{column}" = ?',
                    ("shared-value",),
                ).all()
                assert any(index in row[3] for row in plan)

        # Duplicate and NULL values are valid for all three non-unique indexes.
        seed_records(engine, "after")
        with engine.connect() as conn:
            for model, column, _ in INDEXES:
                count = conn.exec_driver_sql(
                    f'SELECT count(*) FROM "{model.__tablename__}" WHERE "{column}" = ?',
                    ("shared-value",),
                ).scalar_one()
                assert count == (4 if stage == "missing_indexes" else 2)
    finally:
        engine.dispose()
