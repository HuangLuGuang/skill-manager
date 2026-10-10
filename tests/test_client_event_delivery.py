import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend import models
from backend.client_event_delivery import ClientEventDelivery
from backend.sqlite_db import Base
from tests.test_clients_api import _client


def connect(client, device="events-device", name="events"):
    response = client.post("/api/v1/access/tokens", json={"name": name, "token_type": "client", "bound_client_id": device})
    assert response.status_code == 200, response.text
    headers = {"Authorization": f"Bearer {response.json()['token']}"}
    response = client.post("/api/v1/clients/register", headers=headers, json={
        "client_id": device, "name": device, "hostname": "controlled", "os": "linux", "arch": "amd64", "client_version":"controlled", "agents": [],
    })
    assert response.status_code == 200, response.text
    return headers, f"/api/v1/clients/{device}"


def observation(count=1, **changes):
    details = {"path": "/skills/shared", "signature": "content", "policy_version": "6:4", "trigger": "unverified",
               "action": "record_only", "action_status": "completed", "observation_epoch": "persisted-counter-scope",
               "observation_count": count, "last_seen_at": f"2026-10-03T00:00:{count:02d}Z",
               "first_seen_at": "2026-10-01T00:00:00Z", "first_seen_source": "queued_observation"}
    details.update(changes)
    return {"delivery_id": uuid4().hex, "event_type": "skill_governance_recorded", "agent_type": "codex",
            "skill_name": "shared", "details": details, "observation_count": count, "observed_at": details["last_seen_at"]}


def stored(tmp_path):
    return Session(create_engine(f"sqlite:///{tmp_path / 'clients.db'}"))


def test_delivery_replay_concurrency_and_credential_rotation(tmp_path):
    client = _client(tmp_path)
    headers, root = connect(client)
    body = observation()
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: client.post(root + "/events", headers=headers, json=body), range(12)))
    assert all(r.status_code == 200 for r in responses)
    receipts = [r.json() for r in responses]
    assert len({r["event_id"] for r in receipts}) == 1
    assert all(r["durable"] and r["delivery_id"] == body["delivery_id"] for r in receipts)
    rotated, _ = connect(client, name="rotated")
    assert client.post(root + "/events", headers=rotated, json=body).json() == receipts[0]
    with stored(tmp_path) as db:
        assert db.query(models.ClientEvent).filter_by(event_type=body["event_type"]).count() == 1
        assert db.query(ClientEventDelivery).count() == 1
    conflict = client.post(root + "/events", headers=headers, json={**body, "skill_name": "different"})
    assert conflict.status_code == 409
    assert "client.events_delivery_conflict" in conflict.text
    other_headers, other_root = connect(client, "other-device", "other")
    assert client.post(other_root + "/events", headers=headers, json=body).status_code == 403
    different = client.post(other_root + "/events", headers=other_headers, json=body)
    assert different.status_code == 200
    assert different.json()["event_id"] != receipts[0]["event_id"]


def test_cumulative_counts_times_identity_and_independent_actions(tmp_path):
    client = _client(tmp_path)
    headers, root = connect(client)
    first_id = None
    for n in [1, 3, 2, 3]:
        body = observation(n)
        if n > 1:
            body["details"]["first_seen_at"] = "2026-10-02T00:00:00Z"
        r = client.post(root + "/events", headers=headers, json=body)
        assert r.status_code == 200, r.text
        first_id = first_id or r.json()["event_id"]
        assert first_id == r.json()["event_id"]
    with stored(tmp_path) as db:
        event = db.get(models.ClientEvent, first_id)
        assert event.observation_count == 3
        assert event.last_seen_at == datetime(2026, 10, 3, 0, 0, 3)
        assert json.loads(event.details_json)["first_seen_at"] == "2026-10-01T00:00:00Z"
    for key in ["signature", "path", "policy_version", "action", "action_status", "status", "error_code", "task_id", "observation_epoch"]:
        r = client.post(root + "/events", headers=headers, json=observation(4, **{key: "different"}))
        assert r.status_code == 200, r.text
        assert r.json()["event_id"] != first_id
    for event_type in ["skill_governance_action", "skill_installed", "task_result", "aidr_hook_runtime_received"]:
        ids = set()
        for _ in range(2):
            body = observation()
            body["event_type"] = event_type
            r = client.post(root + "/events", headers=headers, json=body)
            assert r.status_code == 200, r.text
            ids.add(r.json()["event_id"])
            assert client.post(root + "/events", headers=headers, json=body).json()["event_id"] == r.json()["event_id"]
        assert len(ids) == 2


def test_additive_upgrade_keeps_history_and_legacy_contract(tmp_path):
    client = _client(tmp_path)
    headers, root = connect(client)
    with stored(tmp_path) as db:
        old = models.ClientEvent(client_id="events-device", event_type="historical", details_json='{"evidence":"preserved"}', created_at=datetime(2026, 9, 1))
        db.add(old)
        db.commit()
        old_id = old.id
    engine = create_engine(f"sqlite:///{tmp_path / 'clients.db'}")
    ClientEventDelivery.__table__.drop(engine)
    Base.metadata.create_all(engine)
    old_client = {"event_type": "skill_governance_recorded", "details": {"path": "/old", "signature": "old"}}
    a = client.post(root + "/events", headers=headers, json=old_client)
    b = client.post(root + "/events", headers=headers, json=old_client)
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json() and "delivery_id" not in a.json()
    assert client.get(root + "/policy", headers=headers).json()["ordinary_events_protocol"] == 1
    with stored(tmp_path) as db:
        assert db.get(models.ClientEvent, old_id).details_json == '{"evidence":"preserved"}'
        assert db.get(models.ClientEvent, old_id).created_at == datetime(2026, 9, 1)
    # Cumulative migration payloads spanning multiple days never add on retry.
    body = observation(3)
    body["details"]["first_seen_at"] = "2026-09-28T00:00:00Z"
    body["details"]["first_seen_source"] = "queue_created_at"
    for _ in range(5):
        response = client.post(root + "/events", headers=headers, json=body)
        assert response.status_code == 200, response.text
    with stored(tmp_path) as db:
        row = db.get(models.ClientEvent, response.json()["event_id"])
        assert row.observation_count == 3
        assert json.loads(row.details_json)["first_seen_at"] == "2026-09-28T00:00:00Z"
