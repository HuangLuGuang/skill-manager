from backend import models
from backend.aidr_models import AidrHookEvent
from backend.aidr_hook_runtime import HookRuntimeRow
from tests.test_aidr_api import service


def report(**changes):
    return dict(schema_version=1, stream_id="a" * 32, receiver_instance="b" * 32,
                report_sequence="1", control_mode="audit", control_revision="",
                control_code="aidr_hook_audit_only", queued_records=0, **changes)


def send(client, body, target="one"):
    return client.post(f"/api/v1/clients/{target}/aidr/hook-runtime", json=body,
                       headers={"authorization": "Bearer test-one"})


def test_report_is_device_scoped_and_not_authority(service, monkeypatch):
    client, factory = service
    assert client.get("/api/v1/clients/one/aidr/hook-policy").json()["runtime"]["items"] == []
    monkeypatch.setattr("backend.aidr_hook_runtime.time.time", lambda: 1000)
    body = report()
    assert send(client, body).status_code == 200
    assert send(client, body, "two").status_code == 403
    assert client.get("/api/v1/clients/two/aidr/hook-policy").status_code == 404
    monkeypatch.setattr("backend.aidr_hook_runtime.time.time", lambda: 1091)
    assert send(client, body).status_code == 200
    item = client.get("/api/v1/clients/one/aidr/hook-policy").json()["runtime"]["items"][0]
    assert item["code"] == "aidr_hook_runtime_stale" and item["received_at"] == "1000"
    assert not item["matches_published_revision"]
    body.update(report_sequence="2", control_mode="plugin_pre_tool", control_revision="999", control_code="aidr_hook_policy_ready")
    assert send(client, body).status_code == 200
    view = client.get("/api/v1/clients/one/aidr/hook-policy").json()
    assert view["revision"] == "0" and view["policy"] is None
    assert not view["runtime"]["items"][0]["matches_published_revision"]
    assert send(client, report()).status_code == 200
    with factory() as db:
        assert db.query(HookRuntimeRow).one().sequence == 2
        token = db.query(models.AccessToken).filter_by(bound_client_id="one").one()
        token.scopes_json = '["aidr:report-events"]'
        db.commit()
    assert send(client, body).status_code == 403


def test_report_bounds_restart_and_validation(service, monkeypatch):
    client, factory = service
    body = report()
    body["control_revision"] = "1"
    assert send(client, body).status_code == 422
    body = report()
    body["queued_records"] = 100001
    assert send(client, body).status_code == 422
    monkeypatch.setattr("backend.aidr_hook_runtime.time.time", lambda: 1000)
    with factory() as db:
        for i in range(256):
            db.add(HookRuntimeRow(client_id="one", stream_id="a"*32, receiver_instance=f"{i:032x}", sequence=1, received_at=1000, payload='{}'))
        db.commit()
    assert send(client, report()).status_code == 429
    monkeypatch.setattr("backend.aidr_hook_runtime.time.time", lambda: 1000 + 7*86400 + 1)
    assert send(client, report()).status_code == 200
    body = report()
    body["receiver_instance"] = "c"*32
    assert send(client, body).status_code == 200
    items = client.get("/api/v1/clients/one/aidr/hook-policy").json()["runtime"]["items"]
    assert len(items) == 2
    with factory() as db:
        assert db.query(HookRuntimeRow).count() == 2
        assert db.query(AidrHookEvent).count() == 0


def test_upload_pause_telemetry_is_not_an_event_ack(service):
    client, factory = service
    with factory() as db:
        db.get(models.AidrDevice, 'one').enabled = False
        db.commit()
    body = report(upload_code='aidr_upload_reporting_paused', next_upload_at='2026-10-01T00:00:30Z', last_event_ack_at='')
    assert send(client, body).status_code == 200
    view = client.get('/api/v1/clients/one/aidr/hook-policy').json()['runtime']['items'][0]
    assert view['upload_code'] == 'aidr_upload_reporting_paused'
    assert view['last_event_ack_at'] == ''
    # Telemetry remains authenticated while reporting is paused.
    assert send(client, body, 'two').status_code == 403
    bad = {**body, 'upload_code': '', 'report_sequence': '2'}
    assert send(client, bad).status_code == 422
    for field in ('next_upload_at', 'last_event_ack_at'):
        assert send(client, {**body, field: 'not a timestamp'}).status_code == 422
    # Legacy reports remain valid and do not fabricate upload/ACK information.
    legacy = report(); legacy['report_sequence'] = '2'
    assert send(client, legacy).status_code == 200
    view = client.get('/api/v1/clients/one/aidr/hook-policy').json()['runtime']['items'][0]
    assert 'upload_code' not in view and 'last_event_ack_at' not in view
    with factory() as db:
        assert db.query(AidrHookEvent).count() == 0
