"""Upgrade the schemas deployed before and between the Open API batches."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import models
from backend.external_access_models import (
    ExternalApiRequest, ExternalPlatform, ExternalResultEvent, ExternalSkillScan,
    ExternalAgentRegistration, ExternalAgentJob, ExternalGatewayEvent,
    ExternalDeliveryEndpoint, ExternalDelivery, ExternalDeliveryAttempt,
    upgrade_external_access_schema,
)


# Fields absent before the Open API batches; independent of migration declarations.
ADDED_COLUMNS = {
    "access_tokens": ("platform_id", "allowed_department_ids_json"),
    "managed_agents": ("registration_source", "source_platform_id", "external_agent_id",
                       "source_token_id", "source_request_id"),
    "security_scan_tasks": ("trigger_source", "source_platform_id", "external_task_id",
                            "business_request_id", "source_token_id", "source_request_id"),
    "external_api_requests": ("business_request_id", "client_request_id"),
}
NEW_MODELS = (ExternalPlatform, ExternalApiRequest, ExternalSkillScan, ExternalResultEvent,
              ExternalAgentRegistration, ExternalAgentJob, ExternalGatewayEvent,
              ExternalDeliveryEndpoint, ExternalDelivery, ExternalDeliveryAttempt)
EXISTING_MODELS = (models.AccessToken, models.ManagedAgent, models.SecurityScanTask)


def remove_columns(connection, table_name, names):
    for index in inspect(connection).get_indexes(table_name):
        if set(index["column_names"]) & set(names):
            connection.exec_driver_sql(f'DROP INDEX "{index["name"]}"')
    for name in names:
        connection.exec_driver_sql(f'ALTER TABLE "{table_name}" DROP COLUMN "{name}"')


def seed_history(engine):
    with Session(engine) as db:
        db.add_all([
            models.AccessToken(id=1, name="Existing scanner", token_type="scanner",
                               token_hash="test-existing-hash", token_prefix="test",
                               scopes_json='["scanner:submit"]', status="disabled"),
            models.ManagedAgent(id=1, agent_id="existing-agent", name="Existing agent"),
            models.SecurityScanTask(id=1, task_id="existing-task", target_id="target",
                                    policy_id="policy", idempotency_key="existing",
                                    request_fingerprint="fingerprint", created_by="admin",
                                    timeout_at=datetime(2030, 1, 1), status="completed",
                                    policy_snapshot_json='{"version": "old"}'),
        ])
        db.commit()


def history(connection):
    result = {}
    for model in EXISTING_MODELS:
        table = model.__table__
        columns = [c for c in table.c if c.name not in ADDED_COLUMNS[table.name]]
        result[table.name] = connection.execute(select(*columns).order_by(table.c.id)).all()
    return result


@pytest.fixture
def legacy_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'upgrade.db'}", connect_args={"timeout": 10})
    models.Base.metadata.create_all(engine)
    seed_history(engine)
    with engine.begin() as connection:
        for model in NEW_MODELS:
            model.__table__.drop(connection)
        for model in EXISTING_MODELS:
            remove_columns(connection, model.__tablename__, ADDED_COLUMNS[model.__tablename__])
    yield engine
    engine.dispose()


def assert_schema(engine):
    inspector = inspect(engine)
    for model in EXISTING_MODELS + NEW_MODELS:
        table = model.__table__
        actual = {c["name"]: c for c in inspector.get_columns(table.name)}
        assert set(actual) == set(table.c.keys())
        for column in table.c:
            assert actual[column.name]["nullable"] == column.nullable
            assert str(actual[column.name]["type"]) == str(column.type)
        actual_indexes = {i["name"]: (tuple(i["column_names"]), bool(i["unique"]))
                          for i in inspector.get_indexes(table.name)}
        expected_indexes = {i.name: (tuple(c.name for c in i.columns), i.unique)
                            for i in table.indexes}
        assert actual_indexes == expected_indexes
    assert any(c["column_names"] == ["task_id"]
               for c in inspector.get_unique_constraints("external_result_events"))
    registration_constraints = {tuple(c["column_names"]) for c in inspector.get_unique_constraints("external_agent_registrations")}
    assert {("platform_id", "agent_id"), ("managed_agent_id",)} <= registration_constraints


def write_external_records(engine):
    with Session(engine) as db:
        db.add(ExternalPlatform(platform_id="partner", name="Partner", created_by="admin"))
        db.add(models.AccessToken(id=2, name="Open API", token_type="openapi",
                                  token_hash="test-openapi-hash", token_prefix="test",
                                  platform_id="partner", allowed_department_ids_json='["ops"]'))
        db.add(models.ManagedAgent(agent_id="external-agent", name="External agent",
                                   registration_source="external_api", source_platform_id="partner",
                                   external_agent_id="agent-1", source_token_id=2, source_request_id="req-1"))
        db.add(ExternalApiRequest(request_id="req-1", method="POST", platform_id="partner",
                                  token_id=2, business_request_id="business-1"))
        db.add(ExternalSkillScan(task_id="scan-1", source_platform_id="partner", source_token_id=2,
                                source_request_id="req-1", department_id="ops", department_group_id=1,
                                business_request_id="business-1", external_skill_id="skill-1",
                                skill_version="v1", file_sha256="a" * 64, version_id="version-1",
                                scan_run_id="run-1", profile_id="standard", profile_json='{"version":"1"}',
                                callback_id="callback", callback_version="1", status="completed",
                                report_json='{"risk_level":"benign"}', findings_json="[]"))
        db.add(ExternalResultEvent(event_id="event-1", task_id="scan-1", source_platform_id="partner",
                                  callback_id="callback", callback_version="1", payload_json='{"task_id":"scan-1"}'))
        task = db.get(models.SecurityScanTask, 1)
        task.trigger_source = "external_api"
        task.source_platform_id = "partner"
        task.external_task_id = "external-task"
        task.business_request_id = "business-1"
        task.source_token_id = 2
        task.source_request_id = "req-1"
        db.commit()


@pytest.mark.parametrize("stage", ["legacy", "first_batch", "partial"])
def test_upgrade_preserves_history_and_supports_new_records(legacy_engine, stage):
    engine = legacy_engine
    if stage == "first_batch":
        upgrade_external_access_schema(engine)
        with engine.begin() as connection:
            ExternalSkillScan.__table__.drop(connection)
            ExternalResultEvent.__table__.drop(connection)
            remove_columns(connection, "external_api_requests", ADDED_COLUMNS["external_api_requests"])
            connection.exec_driver_sql("INSERT INTO external_api_requests (request_id, method, created_at) "
                                       "VALUES ('old-request', 'GET', '2026-10-19 00:00:00')")
    elif stage == "partial":
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE managed_agents ADD COLUMN source_platform_id VARCHAR(64)")
            connection.exec_driver_sql("UPDATE managed_agents SET source_platform_id = 'recorded-partner'")
            connection.exec_driver_sql("ALTER TABLE access_tokens ADD COLUMN platform_id VARCHAR(64)")
    with engine.connect() as connection:
        before = history(connection)
    upgrade_external_access_schema(engine)
    models.Base.metadata.create_all(engine)
    upgrade_external_access_schema(engine)
    assert_schema(engine)
    with engine.connect() as connection:
        assert history(connection) == before
    with Session(engine) as db:
        token = db.get(models.AccessToken, 1)
        assert token.allowed_department_ids_json == "[]" and token.platform_id is None
        agent = db.get(models.ManagedAgent, 1)
        assert agent.registration_source is None
        assert agent.source_platform_id == ("recorded-partner" if stage == "partial" else None)
        assert db.get(models.SecurityScanTask, 1).trigger_source is None
        if stage == "first_batch":
            assert db.query(ExternalApiRequest).one().business_request_id is None
    write_external_records(engine)
    upgrade_external_access_schema(engine)
    with Session(engine) as db:
        assert db.query(models.AccessToken).filter_by(platform_id="partner").one().allowed_department_ids_json == '["ops"]'
        assert db.query(models.ManagedAgent).filter_by(source_platform_id="partner").one().external_agent_id == "agent-1"
        assert db.query(models.SecurityScanTask).filter_by(business_request_id="business-1").one().source_token_id == 2
        assert db.query(ExternalApiRequest).filter_by(business_request_id="business-1").one().request_id == "req-1"
        assert db.get(ExternalSkillScan, "scan-1").report_json == '{"risk_level":"benign"}'
        assert db.get(ExternalResultEvent, "event-1").payload_json == '{"task_id":"scan-1"}'


def test_fresh_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    try:
        upgrade_external_access_schema(engine)
        models.Base.metadata.create_all(engine)
        upgrade_external_access_schema(engine)
        assert_schema(engine)
    finally:
        engine.dispose()


def test_four_batch_request_history_gains_caller_trace_without_rewriting_sources(legacy_engine):
    engine = legacy_engine
    upgrade_external_access_schema(engine)
    write_external_records(engine)
    with engine.begin() as connection:
        remove_columns(connection, "external_api_requests", ("client_request_id",))
        before = list(connection.exec_driver_sql("SELECT * FROM external_api_requests").mappings())
    upgrade_external_access_schema(engine)
    upgrade_external_access_schema(engine)
    assert_schema(engine)
    with engine.connect() as connection:
        after = list(connection.exec_driver_sql("SELECT * FROM external_api_requests").mappings())
        assert [{key: row[key] for key in before[0]} for row in after] == before
    with Session(engine) as db:
        old = db.query(ExternalApiRequest).one()
        assert old.client_request_id is None
        for n in range(2):
            db.add(ExternalApiRequest(request_id=f"new-{n}", client_request_id="same-caller-id", method="GET"))
        db.commit()
        assert db.query(ExternalApiRequest).filter_by(client_request_id="same-caller-id").count() == 2
        assert db.get(ExternalSkillScan, "scan-1").source_request_id == old.request_id


def test_missing_indexes_are_repaired_and_uniqueness_enforced(legacy_engine):
    engine = legacy_engine
    upgrade_external_access_schema(engine)
    write_external_records(engine)
    with engine.begin() as connection:
        for model in EXISTING_MODELS + NEW_MODELS:
            for index in model.__table__.indexes:
                if model in NEW_MODELS or any(c.name in ADDED_COLUMNS[model.__tablename__] for c in index.columns):
                    index.drop(connection)
    upgrade_external_access_schema(engine)
    assert_schema(engine)
    with Session(engine) as db:
        db.add(models.ManagedAgent(agent_id="duplicate", name="Duplicate", source_platform_id="partner", external_agent_id="agent-1"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(ExternalApiRequest(request_id="req-1", method="GET"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(ExternalResultEvent(event_id="duplicate", task_id="scan-1", source_platform_id="partner",
                                  callback_id="callback", callback_version="1", payload_json="{}"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add_all([models.ManagedAgent(agent_id="other-partner", name="Other", source_platform_id="other", external_agent_id="agent-1"),
                    models.ManagedAgent(agent_id="internal", name="Internal")])
        db.commit()


def test_failed_migration_rolls_back_ddl_and_can_retry(legacy_engine):
    engine = legacy_engine
    with engine.connect() as connection:
        before = history(connection)

    def fail_index(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("CREATE INDEX ix_external_skill_scans_"):
            raise RuntimeError("simulated migration interruption")

    event.listen(engine, "before_cursor_execute", fail_index)
    try:
        with pytest.raises(RuntimeError, match="simulated migration interruption"):
            upgrade_external_access_schema(engine)
    finally:
        event.remove(engine, "before_cursor_execute", fail_index)
    inspector = inspect(engine)
    for model in NEW_MODELS:
        assert not inspector.has_table(model.__tablename__)
    for model in EXISTING_MODELS:
        names = {c["name"] for c in inspector.get_columns(model.__tablename__)}
        assert not names.intersection(ADDED_COLUMNS[model.__tablename__])
    with engine.connect() as connection:
        assert history(connection) == before
    upgrade_external_access_schema(engine)
    assert_schema(engine)


def test_concurrent_migration_starts(legacy_engine):
    barrier = Barrier(2)

    def migrate():
        barrier.wait(timeout=10)
        upgrade_external_access_schema(legacy_engine)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(migrate) for _ in range(2)]
        for future in futures:
            future.result(timeout=30)
    assert_schema(legacy_engine)


def test_fourth_batch_upgrade_keeps_third_batch_events(legacy_engine):
    engine = legacy_engine
    upgrade_external_access_schema(engine)
    write_external_records(engine)
    with Session(engine) as db:
        db.add(ExternalAgentJob(task_id="eval-1", kind="evaluation", registration_id="reg-1", platform_id="partner",
            department_id="ops", department_group_id=1, agent_id="agent-1", target_revision=2, credential_id="cred-2",
            registration_json='{"agent_id":"agent-1"}', profile_json='{"version":"1"}', status="succeeded",
            report_json='{"risk_level":"suspicious","report_version":1}'))
        db.add(ExternalGatewayEvent(task_id="eval-1", gateway_id="gateway", gateway_version="1",
            payload_json='{"schema_version":"agent-evaluation-result.v1"}', status="pending"))
        db.commit()
    with engine.begin() as connection:
        for model in (ExternalDeliveryEndpoint, ExternalDelivery, ExternalDeliveryAttempt):
            model.__table__.drop(connection)
        before = {model: connection.execute(select(model.__table__)).all() for model in
                  (ExternalAgentJob, ExternalGatewayEvent, ExternalSkillScan, ExternalResultEvent)}
    upgrade_external_access_schema(engine)
    upgrade_external_access_schema(engine)
    assert_schema(engine)
    with engine.connect() as connection:
        for model, values in before.items():
            assert connection.execute(select(model.__table__)).all() == values


def test_third_batch_upgrade_keeps_second_batch_reports(legacy_engine):
    engine = legacy_engine
    upgrade_external_access_schema(engine)
    write_external_records(engine)
    with engine.begin() as connection:
        for model in (ExternalAgentRegistration, ExternalAgentJob, ExternalGatewayEvent):
            model.__table__.drop(connection)
    upgrade_external_access_schema(engine)
    upgrade_external_access_schema(engine)
    assert_schema(engine)
    with Session(engine) as db:
        assert db.get(ExternalSkillScan, "scan-1").report_json == '{"risk_level":"benign"}'
        assert db.get(ExternalResultEvent, "event-1").payload_json == '{"task_id":"scan-1"}'
        assert db.get(models.AccessToken, 2).platform_id == "partner"
        assert db.query(ExternalApiRequest).filter_by(request_id="req-1").one().business_request_id == "business-1"


@pytest.mark.parametrize("shared_database", [False, True], ids=["separate", "shared"])
def test_registry_snapshot_table_upgrade_preserves_old_reports(legacy_engine, tmp_path, monkeypatch, shared_database):
    from agent_manager.core.models import RegistryEntry, ScanRun, SkillOrigin, SkillStatus, SourceInfo, VettingResult
    from agent_manager.core.registry import Registry

    monkeypatch.setenv("AGENT_MANAGER_DATA_DIR", str(tmp_path / "registry"))
    if shared_database:
        monkeypatch.setenv("AGENT_MANAGER_REGISTRY_SQLITE_PATH", legacy_engine.url.database)
        data_dir = None
    else:
        data_dir = tmp_path / "registry"
    registry = Registry(data_dir=data_dir)
    report = {"findings": [{"title": "Existing finding", "severity": "HIGH"}]}
    entry = RegistryEntry(skill_id="old-version", name="existing-skill", description="Existing skill",
                          source=SourceInfo(origin=SkillOrigin.LOCAL), status=SkillStatus.VETTED,
                          vetting=VettingResult(scan_report=report, findings_count=1))
    registry.add(entry)
    run = ScanRun(scan_run_id="old-run", version_id=entry.skill_id,
                  scan_context_fingerprint="old-context", status="COMPLETED")
    registry.add_scan_run(run)
    with registry._connect() as connection:
        connection.execute("DROP TABLE skill_scan_run_reports")
        before = {table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
                  for table in ("skill_registry", "skill_scan_runs", "skill_scan_reports")}
    upgrade_external_access_schema(legacy_engine)
    registry = Registry(data_dir=data_dir)
    with registry._connect() as connection:
        for table, rows in before.items():
            assert [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")] == rows
    assert registry.get_by_id(entry.skill_id).vetting.scan_report == report
    assert registry.get_scan_run_report(run.scan_run_id) is None
    new_run = ScanRun(scan_run_id="new-run", version_id=entry.skill_id, scan_context_fingerprint="new-context")
    registry.add_scan_run(new_run)
    new_run.status = "COMPLETED"
    snapshot = {"scan_report": {"findings": []}, "risk_level": "benign"}
    registry.update_scan_run(new_run, report=snapshot)
    registry = Registry(data_dir=data_dir)
    upgrade_external_access_schema(legacy_engine)
    assert registry.get_scan_run_report(new_run.scan_run_id) == snapshot
    assert registry.get_scan_run_report(run.scan_run_id) is None
    assert_schema(legacy_engine)
