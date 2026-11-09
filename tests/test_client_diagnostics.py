from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from backend import auth, models
from backend.client_diagnostics import DiagnosticLog
from backend.routers import client_diagnostics
from tests.test_clients_api import _client
from tests.test_client_event_delivery import connect, stored


def test_diagnostic_indexes_upgrade_and_repeated_startup(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.schema import DropIndex
    from backend.client_diagnostics import ensure_indexes

    engine = create_engine(f"sqlite:///{tmp_path / 'indexes.db'}")
    DiagnosticLog.__table__.create(engine)
    incident = next(i for i in DiagnosticLog.__table__.indexes if i.name == 'ix_client_diagnostics_incident')
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO client_diagnostic_logs (client_id, record_id, occurred_at, received_at, level, module, event, version, content) VALUES ('test', 'one', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'ERROR', 'test', 'sync_failed', 'test', '{}')")
        connection.execute(DropIndex(incident))
    ensure_indexes(engine)
    engine.dispose()
    ensure_indexes(engine)
    ensure_indexes(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM sqlite_master WHERE type='index' AND name='ix_client_diagnostics_incident'").scalar_one() == 1
        assert connection.exec_driver_sql("SELECT count(*) FROM client_diagnostic_logs").scalar_one() == 1
    engine.dispose()


def setup(tmp_path):
    client = _client(tmp_path)
    client.app.include_router(client_diagnostics.router, prefix="/api")
    client.app.dependency_overrides[auth.get_current_active_user] = lambda: models.User(username="admin", role="super_admin", is_active=True)
    headers, root = connect(client)
    return client, headers, root


def record(id="one", **changes):
    return dict(id=id, time="2026-11-09T12:00:00+08:00", level="ERROR", module="receiver", event="sync_failed", version="test", pid=1, fields={"error": "token=ORIGINAL\nnext line"}, **changes)


def test_error_policy_includes_recovery_but_not_ordinary_info(tmp_path):
    client, headers, root = setup(tmp_path)
    incident = "a" * 32
    failure = dict(record(), fields={"error": "connection refused", "incident_id": incident})
    recovery = dict(record("recovered"), level="INFO", event="sync_recovered", fields={"incident_id": incident, "failure_count": 20})
    ordinary = dict(record("ordinary"), level="INFO", event="success")
    invalid_recovery = dict(recovery, id="invalid", fields={"incident_id": "bad"})
    response = client.post(root + "/diagnostics/batch", headers=headers, json={"records": [failure, recovery, ordinary, invalid_recovery]})
    assert response.status_code == 200, response.text
    logs = client.get(root + "/diagnostics/logs").json()
    assert logs["total"] == 2
    assert {row["level"] for row in logs["items"]} == {"ERROR", "INFO"}
    client.put("/api/v1/clients/diagnostics/settings", json={"level": "OFF"})
    assert client.post(root + "/diagnostics/batch", headers=headers, json={"records": [dict(recovery, id="off")]}).status_code == 200
    assert client.get(root + "/diagnostics/logs").json()["total"] == 2


def test_config_inheritance_bound_ingest_dedup_and_raw_download(tmp_path):
    client, headers, root = setup(tmp_path)
    settings = "/api/v1/clients/diagnostics/settings"
    assert client.get(settings).json()["effective_level"] == "ERROR"
    assert client.put(settings, json={"level": "WARN"}).status_code == 200
    assert client.get(root + "/diagnostics/config", headers=headers).json() == {"level": "INHERIT", "effective_level": "WARN", "expires_at": None}
    body = {"records": [record()]}
    for _ in range(2):
        response = client.post(root + "/diagnostics/batch", headers=headers, json=body)
        assert response.status_code == 200, response.text
        assert response.json() == {"acknowledged": ["one"]}
    assert client.get(root + "/diagnostics/logs").json()["total"] == 1
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: client.post(root + "/diagnostics/batch", headers=headers, json=body), range(6)))
    assert all(response.status_code == 200 for response in responses)
    assert client.get(root + "/diagnostics/logs").json()["total"] == 1
    exported = client.get(root + "/diagnostics/logs?download=true")
    assert "token=ORIGINAL" in exported.text
    assert exported.headers["cache-control"] == "no-store"
    _, other_root = connect(client, "other", "other")
    assert client.post(other_root + "/diagnostics/batch", headers=headers, json=body).status_code == 403
    assert client.put(settings + "?client_id=events-device", json={"level": "OFF"}).status_code == 200
    assert client.post(root + "/diagnostics/batch", headers=headers, json={"records": [record("two")]}).status_code == 200
    assert client.get(root + "/diagnostics/logs").json()["total"] == 1
    assert client.put(settings, json={"level": "INHERIT"}).status_code == 422


def test_limits_filters_and_permissions(tmp_path, monkeypatch):
    client, headers, root = setup(tmp_path)
    client.put("/api/v1/clients/diagnostics/settings", json={"level": "INFO"})
    for value in [dict(record(), fields={"error": "x" * 65536}), dict(record(), time="bad"), dict(record(), level="FATAL")]:
        response = client.post(root + "/diagnostics/batch", headers=headers, json={"records": [value]})
        assert response.status_code == 422
        assert "client.diagnostics.invalid" in response.text
    assert client.post(root + "/diagnostics/batch", headers=headers, content=b"x" * (1024 * 1024 + 1)).status_code == 422
    assert client.post(root + "/diagnostics/batch", headers=headers, json={"records": [record()]}).status_code == 200
    assert client.get(root + "/diagnostics/logs?keyword=ORIGINAL&module=receiver&version=test&level=ERROR").json()["total"] == 1
    assert client.get(root + "/diagnostics/logs?keyword=%25").json()["total"] == 0
    assert client.get(root + "/diagnostics/logs?start=2026-11-09T04:00:00Z&end=2026-11-09T04:00:00Z").json()["total"] == 1
    assert client.get(root + "/diagnostics/logs?start=2026-11-09").status_code == 422
    with stored(tmp_path) as db:
        row = db.query(DiagnosticLog).one()
        row.received_at = datetime.utcnow() - timedelta(days=8)
        db.commit()
    assert client.get(root + "/diagnostics/logs").json()["total"] == 0
    from backend import client_diagnostics as storage
    monkeypatch.setattr(storage, "SessionLocal", lambda: stored(tmp_path))
    assert storage.cleanup_once() is False
    with stored(tmp_path) as db:
        assert db.query(DiagnosticLog).count() == 0
        audits = db.query(models.ManagementAudit).all()
        assert any(row.action == "diagnostics" for row in audits)
        assert all("ORIGINAL" not in row.details_json for row in audits)
    client.app.dependency_overrides[auth.get_current_active_user] = lambda: models.User(username="admin", role="user")
    monkeypatch.setattr(client_diagnostics.iam, "permission_codes", lambda db, user: {"clients:view"})
    assert client.get(root + "/diagnostics/logs").status_code == 403
    monkeypatch.setattr(client_diagnostics.iam, "permission_codes", lambda db, user: {"clients:diagnostics"})
    assert client.get(root + "/diagnostics/logs?download=true").status_code == 403
    assert client.get(root + "/diagnostics/logs").status_code == 200
    client.app.dependency_overrides[auth.get_current_active_user] = lambda: models.User(username="other", role="user")
    assert client.get(root + "/diagnostics/logs").status_code == 404


def test_defaults_preserve_saved_settings_and_expire_only_new_debug(tmp_path):
    from backend.client_diagnostics import DiagnosticSettings, DiagnosticDebugLease, configuration
    client, headers, root = setup(tmp_path)
    settings = "/api/v1/clients/diagnostics/settings"
    with stored(tmp_path) as db:
        assert configuration(db)["effective_level"] == "ERROR"
        db.add(DiagnosticSettings(scope="global", level="OFF"))
        db.add(DiagnosticSettings(scope="client:events-device", level="DEBUG"))
        db.commit()
        assert configuration(db)["effective_level"] == "OFF"
        assert configuration(db, "events-device")["effective_level"] == "DEBUG"
        assert configuration(db, "events-device")["expires_at"] is None
        assert db.query(DiagnosticDebugLease).count() == 0
    response = client.put(settings + "?client_id=events-device", json={"level": "INFO"})
    assert response.status_code == 200
    expiry = datetime.fromisoformat(response.json()["expires_at"].replace("Z", "+00:00"))
    assert 3590 < (expiry.replace(tzinfo=None) - datetime.utcnow()).total_seconds() <= 3600
    with stored(tmp_path) as db:
        lease = db.get(DiagnosticDebugLease, "client:events-device")
        lease.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get(root + "/diagnostics/config", headers=headers).json()["effective_level"] == "ERROR"
    assert client.get(settings).json()["effective_level"] == "OFF"
    info = dict(record(), level="INFO")
    client.post(root + "/diagnostics/batch", headers=headers, json={"records": [info]})
    assert client.get(root + "/diagnostics/logs").json()["total"] == 0
    client.put(settings, json={"level": "DEBUG"})
    client.put(settings + "?client_id=events-device", json={"level": "INHERIT"})
    assert client.get(root + "/diagnostics/config", headers=headers).json()["expires_at"]


def test_capacity_accounting_backfill_dedup_and_bounded_cleanup(tmp_path, monkeypatch):
    from sqlalchemy import text
    from backend import client_diagnostics as storage
    client, headers, root = setup(tmp_path)
    monkeypatch.setattr(storage, "SessionLocal", lambda: stored(tmp_path))
    monkeypatch.setattr(storage, "MAX_CLIENT_RECORDS", 3)
    with stored(tmp_path) as db:
        for i in range(5):
            db.add(DiagnosticLog(client_id="events-device", record_id=f"old{i}", occurred_at=datetime.utcnow(),
                                 received_at=datetime.utcnow()-timedelta(hours=5-i), level="ERROR", module="test", event="test", version="test", content='{"text":"原文"}'))
        db.commit()
        storage.initialize_usage(db)
        db.commit()
        assert db.execute(text("SELECT bytes FROM client_diagnostic_usage WHERE scope='global'")).scalar() == 5 * len('{"text":"原文"}'.encode())
    assert storage.cleanup_once()
    with stored(tmp_path) as db:
        assert {row.record_id for row in db.query(DiagnosticLog)} == {"old2", "old3", "old4"}
    for _ in range(2):
        assert client.post(root + "/diagnostics/batch", headers=headers, json={"records": [record()]}).status_code == 200
    with stored(tmp_path) as db:
        actual = db.execute(text("SELECT count(*),sum(length(CAST(content AS BLOB))) FROM client_diagnostic_logs")).one()
        usage = db.execute(text("SELECT records,bytes FROM client_diagnostic_usage WHERE scope='global'")).one()
        assert tuple(actual) == tuple(usage)
        assert usage.records == 3
    monkeypatch.setattr(storage, "MAX_CONTENT_BYTES", 1)
    assert storage.cleanup_once()
    with stored(tmp_path) as db:
        assert db.query(DiagnosticLog).count() == 0
        assert db.execute(text("SELECT bytes FROM client_diagnostic_usage WHERE scope='global'")).scalar() == 0
    assert storage.cleanup_once() is False


def test_aggregation_metadata_is_preserved(tmp_path):
    client, headers, root = setup(tmp_path)
    item = dict(record(), aggregation={"repeated_count": 91, "first_at": "2026-11-09T12:00:00+08:00", "last_at": "2026-11-09T12:05:00+08:00"})
    assert client.post(root + "/diagnostics/batch", headers=headers, json={"records": [item]}).status_code == 200
    row = client.get(root + "/diagnostics/logs").json()["items"][0]
    assert row["aggregation"] == item["aggregation"]
    assert row["fields"] == item["fields"]


def test_retention_uses_bounded_batches(tmp_path, monkeypatch):
    from backend import client_diagnostics as storage
    setup(tmp_path)
    monkeypatch.setattr(storage, "SessionLocal", lambda: stored(tmp_path))
    with stored(tmp_path) as db:
        db.add_all(DiagnosticLog(client_id="events-device", record_id=str(i), occurred_at=datetime.utcnow(),
                                 received_at=datetime.utcnow()-timedelta(days=8), level="ERROR", module="test", event="test", version="test", content="{}") for i in range(501))
        db.commit()
    assert storage.cleanup_once() is True
    with stored(tmp_path) as db:
        assert db.query(DiagnosticLog).count() == 1
    assert storage.cleanup_once() is False
