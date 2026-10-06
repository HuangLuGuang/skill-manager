import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

from tests.test_aidr_api import service
from backend import models
from backend.aidr_models import AidrHookBatch, AidrHookEvent


def hook_batch(seq=1):
    return {"schema_version": 1, "client_id": "one", "stream_id": "b"*32, "records": [{
        "event_id": f"{seq:032x}", "source_seq": str(seq), "user_scope": "501",
        "received_at": "2026-09-27T01:02:03Z", "event": {
            "schema_version": 1, "agent": "codex", "hook_event": "SessionStart", "kind": "session.start",
            "session_id": "independent-test-session", "policy": {"version": "0", "enabled": True, "receipt": ""},
            "evidence_digest": "a"*64, "process_relation": "unknown",
        }}]}


def send(client, value=None, target="one", token="one"):
    return client.post(f"/api/v1/clients/{target}/aidr/hooks:batch", content=json.dumps(value or hook_batch(), separators=(",", ":")), headers={"authorization": "Bearer test-"+token, "content-type": "application/json"})


def test_hook_atomic_dedup_and_conflicting_sequence(service):
    client, factory = service
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: send(client), range(8)))
    assert all(r.status_code == 200 and r.json()["durable"] for r in responses)
    raw = json.dumps(hook_batch(), separators=(",", ":")).encode()
    assert responses[0].json()["digest"] == hashlib.sha256(raw).hexdigest()
    with factory() as db:
        assert db.query(AidrHookEvent).count() == db.query(AidrHookBatch).count() == 1
    changed = hook_batch()
    changed["records"][0]["event"]["session_id"] = "different"
    assert send(client, changed).status_code == 409
    changed = hook_batch()
    changed["records"][0]["event_id"] = "f"*32
    assert send(client, changed).status_code == 409
    with factory() as db:
        assert db.query(AidrHookEvent).count() == db.query(AidrHookBatch).count() == 1
    items = client.get("/api/v1/clients/one/aidr/hooks").json()["items"]
    assert len(items) == 1 and items[0]["record"]["event"]["process_relation"] == "unknown"
    assert "receiver_instance" not in items[0]["record"]  # old projections stay byte-compatible


def test_hook_binding_permissions_and_payload_boundaries(service):
    client, factory = service
    assert send(client, target="two").status_code == 403
    assert client.get("/api/v1/clients/two/aidr/hooks").status_code == 404
    value = hook_batch(); value["client_id"] = "two"
    assert send(client, value).status_code == 403
    value = hook_batch(); value["records"][0]["event"]["prompt"] = "SYNTHETIC-PRIVATE-PROMPT"
    result = send(client, value)
    assert result.status_code == 422 and "SYNTHETIC-PRIVATE-PROMPT" not in result.text
    value = hook_batch(); value["records"][0]["source_seq"] = str(2**63)
    assert send(client, value).status_code == 422
    value = hook_batch(); value["records"][0]["event"]["process_relation"] = "confirmed"
    assert send(client, value).status_code == 422
    with factory() as db:
        db.query(models.AccessToken).filter_by(name="one").one().scopes_json = '["aidr:heartbeat"]'
        db.commit()
    assert send(client).status_code == 403
    with factory() as db:
        db.query(models.AccessToken).filter_by(name="one").one().scopes_json = '["aidr:report-events"]'
        db.get(models.AidrDevice, "one").enabled = False
        db.commit()
    assert send(client).status_code == 403


def test_bridge_provenance_is_bounded_immutable_and_not_tool_authority(service):
    client, factory = service
    value = hook_batch()
    peer = {"boot_id": "11111111-1111-1111-1111-111111111111", "pid": "123", "pidversion": "456",
        "start_us": "9007199254740993", "method": "macos_socket_audit_token_sysctl", "role": "ipc_bridge"}
    value["records"][0]["bridge_process"] = peer
    for _ in range(2):
        assert send(client, value).status_code == 200
    saved = client.get("/api/v1/clients/one/aidr/hooks").json()["items"][0]["record"]
    assert saved["bridge_process"] == peer
    assert saved["event"]["process_relation"] == "unknown"
    for key, invalid in [("pid", "2147483648"), ("pidversion", "4294967296"), ("start_us", "9223372036854775808"), ("role", "tool_process"), ("method", "host_json"), ("pid", 123)]:
        changed = copy.deepcopy(value)
        changed["records"][0]["bridge_process"][key] = invalid
        assert send(client, changed).status_code == 422
    changed = copy.deepcopy(value)
    changed["records"][0]["bridge_process"]["pidversion"] = "457"
    assert send(client, changed).status_code == 409
    with factory() as db:
        assert db.query(AidrHookEvent).count() == 1


def test_hook_server_policy_receipt_and_whitelist(service):
    client, factory = service
    value = hook_batch()
    event = value["records"][0]["event"]
    event.update(hook_event="PreToolUse", kind="tool.pre", native_call_id="call", turn_id="turn", tool="Bash", input_digest="c"*64)
    event["behavior"] = {"version": 3, "policy": copy.deepcopy(event["policy"]), "body_omitted": False,
        "category": "command", "method": "direct_fields", "actions": [{"tool": "Bash", "category": "command", "command": "echo --password='synthetic-test-secret'", "cwd": "", "targets": [], "source_fields": ["command"]}],
        "status": "unknown", "result_basis": [], "redacted": False, "truncated": False, "uncertainty": []}
    assert send(client, value).status_code == 422
    with factory() as db:
        db.add(models.SystemConfig(key="aidr_audit_redaction", value=json.dumps({"enabled": False, "version": "2"})))
        db.commit()
    policy = client.post("/api/v1/clients/one/aidr/audit-policy", json={"stream_id": "b"*32, "last_sequence": "0"}, headers={"authorization": "Bearer test-one"}).json()
    event["policy"] = event["behavior"]["policy"] = policy
    assert send(client, value).status_code == 200
    with factory() as db:
        db.get(models.SystemConfig, "aidr_audit_redaction").value = json.dumps({"enabled": True, "version": "3"})
        db.commit()
    newer = client.post("/api/v1/clients/one/aidr/audit-policy", json={"stream_id": "b"*32, "last_sequence": "1", "applied_receipt": policy["receipt"], "applied_after": "0"}, headers={"authorization": "Bearer test-one"}).json()
    assert newer["enabled"] is True
    # ACK application closes the previous policy after the actual durable frontier.
    client.post("/api/v1/clients/one/aidr/audit-policy", json={"stream_id": "b"*32, "last_sequence": "1", "applied_receipt": newer["receipt"], "applied_after": "1"}, headers={"authorization": "Bearer test-one"})
    assert send(client, value).status_code == 200  # frozen historical retry
    value["records"][0].update(source_seq="2", event_id="d"*32)
    assert send(client, value).status_code == 409  # old policy beyond its range
    event["policy"] = event["behavior"]["policy"] = {**policy, "receipt": "e"*32}
    assert send(client, value).status_code == 409
    lifecycle = hook_batch(3)
    lifecycle["records"][0]["event"]["policy"] = {**policy, "receipt": "e"*32}
    assert send(client, lifecycle).status_code == 409
