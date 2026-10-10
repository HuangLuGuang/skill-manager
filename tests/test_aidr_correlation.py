import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from backend.aidr_models import AidrHookEvent
from backend.aidr_correlation import install_indexes
from tests.test_aidr_api import service
from tests.test_aidr_operations import event, upload, operations
from tests.test_aidr_hooks import hook_batch, send


def test_bridge_os_evidence_requires_every_identity_field_and_keeps_scope(service):
    from backend.aidr_correlation import bridge_evidence
    from backend.aidr_enforcement import AidrRuntimeRecord
    client, factory = service
    peer = {"boot_id": "11111111-1111-1111-1111-111111111111", "pid": "123",
        "pidversion": "456", "start_us": "9007199254740993", "method": "macos_socket_audit_token_sysctl", "role": "ipc_bridge"}
    record = {"bridge_process": peer}
    original = json.dumps(record, sort_keys=True)
    def insert(db, *, device="one", changes=None, transition="exec", root=None):
        identity = {**peer, **(changes or {})}
        payload = {"boot_id": identity["boot_id"], "process": {key: identity[key] for key in ("pid", "pidversion", "start_us")},
            "time_ns": "1800000000000000000", "transition": transition, "relation": "inherited", "root": root}
        db.add(AidrRuntimeRecord(client_id=device, monitor_id="22222222-2222-2222-2222-222222222222",
            sequence=str(db.query(AidrRuntimeRecord).count()+1), kind="process", payload_json=json.dumps(payload), received_at="2026-09-27T00:00:00Z"))
        db.commit()
    with factory() as db:
        assert bridge_evidence(db, "one", {})["code"] == "aidr_bridge_not_reported"
        for field, value in [("pid", "124"), ("pidversion", "457"), ("start_us", "9007199254740992"), ("boot_id", "33333333-3333-3333-3333-333333333333")]:
            insert(db, changes={field: value})
        insert(db, device="two")
        assert bridge_evidence(db, "one", record)["code"] == "aidr_bridge_no_os_evidence"
        root = {"pid": "10", "pidversion": "11", "start_us": "9007199254740000"}
        insert(db, root=root)
        matched = bridge_evidence(db, "one", record)
        assert matched["relation"] == "matched" and matched["items"][0]["root"] == root
        insert(db, transition="exit", root=root)
        assert bridge_evidence(db, "one", record)["items"][0]["transition"] == "exit"
        insert(db, root={**root, "pidversion": "12"})
        conflict = bridge_evidence(db, "one", record)
        assert conflict["relation"] == "conflicting" and len(conflict["items"]) == 3
        insert(db, root=root)
        insert(db, root=root)
        limit = bridge_evidence(db, "one", record)
        assert limit["code"] == "aidr_bridge_evidence_budget" and limit["truncated"] and limit["items"] == []
        install_indexes(db.connection())
        plan = db.connection().exec_driver_sql("""EXPLAIN QUERY PLAN SELECT id FROM aidr_runtime_records
            WHERE client_id='one' AND kind='process' AND json_extract(payload_json,'$.boot_id')='b'
            AND json_extract(payload_json,'$.process.pid')='1' AND json_extract(payload_json,'$.process.pidversion')='2'
            AND json_extract(payload_json,'$.process.start_us')='3' ORDER BY id DESC LIMIT 5""").all()
        assert "ix_aidr_runtime_process_identity" in str(plan)
    assert json.dumps(record, sort_keys=True) == original


def add_hook(factory, call, *, client_id="one", user="501", tool="Bash", subagent="", count=1, hook_turn=None):
    with factory() as db:
        for index in range(count):
            eid = hashlib.md5(f"{client_id}:{user}:{call['session_id']}:{call['native_call_id']}:{hook_turn}:{index}".encode()).hexdigest()
            record = {"event_id": eid, "user_scope": user, "received_at": "2026-09-27T00:00:00Z",
                      "event": {**{k: call[k] for k in ("agent", "session_id", "turn_id", "native_call_id")},
                                "native_agent_id": subagent, "hook_event": "PostToolUse",
                                "tool": tool, "behavior": {"status": "unknown", "actions": [{"command": "BODY_NOT_COPIED"}]}}}
            if hook_turn is not None:
                record["event"]["turn_id"] = hook_turn
            db.add(AidrHookEvent(client_id=client_id, stream_id=eid, event_id=eid,
                source_seq=1, content_hash="a" * 64, payload_json=json.dumps(record)))
        db.commit()


def test_twenty_namespaces_late_hooks_no_duplicate_operations(service):
    client, factory = service
    calls = [event("tool_call", agent="claude", tool="Bash", session=f"session-{i}", turn="") for i in range(20)]
    for call in calls:
        assert upload(client, call).status_code == 200
    assert all(x["hook_evidence"]["code"] == "aidr_link_no_matching_hook" for x in operations(client)["items"])
    for call in reversed(calls):
        add_hook(factory, call)
    rows = operations(client)["items"]
    assert len(rows) == 20
    assert all(x["hook_evidence"]["relation"] == "inferred" and len(x["hook_evidence"]["items"]) == 1 for x in rows)
    assert all(x["process_relation"] == "unknown" and x["status"] == "missing_result" for x in rows)
    assert "BODY_NOT_COPIED" not in json.dumps(rows)
    assert upload(client, *calls).status_code == 200
    assert len(operations(client)["items"]) == 20
    assert client.get("/api/v1/clients/two/aidr/operations").status_code == 404


def test_operation_presents_three_sources_without_claiming_tool_process(service):
    from backend.aidr_enforcement import AidrRuntimeRecord
    client, factory = service
    call = event("tool_call", tool="Bash")
    assert upload(client, call).status_code == 200
    add_hook(factory, call)
    peer = {"boot_id": "11111111-1111-1111-1111-111111111111", "pid": "123", "pidversion": "456",
        "start_us": "9007199254740993", "method": "macos_socket_audit_token_sysctl", "role": "ipc_bridge"}
    with factory() as db:
        hook = db.query(AidrHookEvent).one()
        payload = json.loads(hook.payload_json)
        payload["bridge_process"] = peer
        hook.payload_json = json.dumps(payload)
        native = {"boot_id": peer["boot_id"], "process": {key: peer[key] for key in ("pid", "pidversion", "start_us")},
            "time_ns": "1800000000000000000", "transition": "exec", "relation": "unknown"}
        row = AidrRuntimeRecord(client_id="one", monitor_id="22222222-2222-2222-2222-222222222222", sequence="9007199254740995",
            kind="process", payload_json=json.dumps(native), received_at="2026-09-27T00:00:00Z")
        db.add(row)
        db.commit()
        expected_id = str(row.id)
        original_hook, original_os = hook.payload_json, row.payload_json
    for _ in range(2):
        result = operations(client)["items"]
        assert len(result) == 1 and result[0]["process_relation"] == "unknown"
        linked = result[0]["hook_evidence"]
        assert linked["relation"] == "inferred"
        bridge = linked["items"][0]["bridge_evidence"]
        assert bridge["relation"] == "matched" and bridge["identity"] == peer
        assert bridge["items"][0]["id"] == expected_id
        assert bridge["items"][0]["sequence"] == "9007199254740995"
    with factory() as db:
        assert db.query(AidrHookEvent).one().payload_json == original_hook
        assert db.query(AidrRuntimeRecord).one().payload_json == original_os


def test_ambiguous_sources_users_shared_services_and_budget(service):
    client, factory = service
    call = event("tool_call", agent="claude", tool="Bash", turn="")
    assert upload(client, call).status_code == 200
    add_hook(factory, call, client_id="two")
    assert operations(client)["items"][0]["hook_evidence"]["code"] == "aidr_link_no_matching_hook"
    add_hook(factory, call)
    add_hook(factory, call, user="502")
    assert operations(client)["items"][0]["hook_evidence"]["code"] == "aidr_link_source_ambiguous"
    other = event("tool_call", agent="claude", tool="Bash", turn="", source="b"*64)
    assert upload(client, other).status_code == 200
    assert all(r["hook_evidence"]["code"] == "aidr_link_source_ambiguous" for r in operations(client)["items"])
    for name, kwargs, expected in [
        ("shared-mcp", {"subagent": "worker"}, "aidr_link_source_ambiguous"),
        ("shell-wrapper", {"tool": "exec"}, "aidr_link_tool_unverified"),
        ("burst", {"count": 17}, "aidr_link_evidence_budget"),
    ]:
        c = event("tool_call", agent="claude", tool="Bash", call=name, turn="")
        assert upload(client, c).status_code == 200
        add_hook(factory, c, **kwargs)
        r = next(r for r in operations(client)["items"] if r["call"]["native_call_id"] == name)
        assert r["hook_evidence"]["code"] == expected
        assert r["hook_evidence"]["items"] == []


def test_indexes_are_additive_and_idempotent(service):
    _, factory = service
    with factory() as db:
        install_indexes(db.connection())
        install_indexes(db.connection())
        plan = db.connection().exec_driver_sql("""EXPLAIN QUERY PLAN SELECT id FROM aidr_hook_events
          WHERE client_id='one' AND json_extract(payload_json,'$.event.agent')='claude'
          AND json_extract(payload_json,'$.event.session_id')='s'
          AND json_extract(payload_json,'$.event.turn_id')=''
          AND json_extract(payload_json,'$.event.native_call_id')='c' ORDER BY id LIMIT 17""").all()
        assert "ix_aidr_hook_native_call" in str(plan)


def test_codex_requires_turn_and_does_not_match_other_turn(service):
    client, factory = service
    c = event("tool_call", tool="Bash", turn="turn-a")
    assert upload(client, c).status_code == 200
    add_hook(factory, {**c, "turn_id": "turn-b"})
    assert operations(client)["items"][0]["hook_evidence"]["code"] == "aidr_link_no_matching_hook"
    missing = event("tool_call", call="missing-turn", tool="Bash", turn="")
    assert upload(client, missing).status_code == 200
    add_hook(factory, missing)
    row = next(r for r in operations(client)["items"] if r["call"]["native_call_id"] == "missing-turn")
    assert row["hook_evidence"]["code"] == "aidr_link_identity_missing"


def test_claude_prompt_id_absent_from_logs_and_conflicting_prompts(service):
    client, factory = service
    call = event("tool_call", agent="claude", tool="Bash", turn="")
    assert upload(client, call).status_code == 200
    add_hook(factory, call, hook_turn="native-prompt-a")
    assert operations(client)["items"][0]["hook_evidence"]["relation"] == "inferred"
    add_hook(factory, call, hook_turn="native-prompt-b")
    link = operations(client)["items"][0]["hook_evidence"]
    assert link["relation"] == "unknown" and link["code"] == "aidr_link_source_ambiguous"


def test_concurrent_twenty_calls_real_ingestion_and_frozen_retries(service):
    """Concurrent protocol inputs, not a native Agent or OS attribution test."""
    client, factory = service
    barrier = Barrier(20)

    def one(index):
        # Reuse the call ID across sessions, and the session across Codex turns.
        # The expected namespace comes from the fixture, not a correlation helper.
        agent = "claude" if index < 10 else "codex"
        session = f"parallel-{index}" if agent == "claude" else "parallel-codex"
        turn = "" if agent == "claude" else f"turn-{index}"
        call = event("tool_call", agent=agent, session=session, turn=turn, tool="Bash")
        result = event("tool_result", agent=agent, session=session, turn=turn)
        batch = hook_batch(index + 1)
        record = batch["records"][0]
        record["event"].update(agent=agent, session_id=session, turn_id=turn,
            native_call_id="same-call", tool="Bash", hook_event="PostToolUse", kind="tool.post")
        record["event"]["behavior"] = {
            "version": 3, "policy": record["event"]["policy"], "body_omitted": True,
            "category": "unknown", "method": "result_fields", "actions": [],
            "status": "unknown", "result_basis": [], "redacted": False,
            "truncated": False, "uncertainty": [],
        }
        barrier.wait(timeout=15)
        # Both late result and result-first paths must converge without rewriting
        # either source. Each retry is the same immutable protocol body.
        log_inputs = (result, call) if index % 2 else (call, result)
        for value in log_inputs:
            response = upload(client, value)
            assert response.status_code == 200, response.text
        for _ in range(2):
            response = send(client, batch)
            assert response.status_code == 200, response.text
            assert response.json()["digest"] == hashlib.sha256(
                json.dumps(batch, separators=(",", ":")).encode()).hexdigest()
        assert upload(client, *log_inputs).status_code == 200
        return (agent, session, turn), record["event_id"]

    with ThreadPoolExecutor(max_workers=20) as pool:
        expected = dict(pool.map(one, range(20)))
    rows = operations(client)["items"]
    assert len(rows) == 20
    for row in rows:
        call = row["call"]
        key = (call["agent"], call["session_id"], call["turn_id"])
        link = row["hook_evidence"]
        assert [item["event_id"] for item in link["items"]] == [expected[key]]
        assert link["relation"] == "inferred"
        assert row["status"] == row["process_relation"] == "unknown"
        assert row["result"]["native_call_id"] == call["native_call_id"]
    from backend.aidr_models import AidrHookBatch, AidrEvent, AidrOperation
    with factory() as db:
        assert db.query(AidrHookEvent).count() == 20
        assert db.query(AidrHookBatch).count() == 20
        assert db.query(AidrEvent).count() == 40
        assert db.query(AidrOperation).count() == 20
