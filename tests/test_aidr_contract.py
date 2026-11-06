import json
from pathlib import Path

import pytest

from backend.aidr_contract import Event, parse_batch
from backend.api_errors import ApiError


VECTORS = Path(__file__).parents[1] / "scanner/internal/aidr/agentlog/testdata/contracts.json"


def test_shared_event_contract():
    vectors = json.loads(VECTORS.read_text())
    for case in vectors:
        if case["valid"]:
            Event.model_validate(case["event"])
        else:
            with pytest.raises(ValueError):
                Event.model_validate(case["event"])


@pytest.mark.parametrize('scope', ['0', '501', 'S-1-5-18', 'S-1-5-21-1234567890-2345678901-3456789012-1001'])
def test_log_user_identity_roundtrip(scope):
    vectors = json.loads(VECTORS.read_text())
    event = next(case['event'] for case in vectors if case['valid'])
    event['user_scope'] = scope
    assert Event.model_validate(event).user_scope == scope


@pytest.mark.parametrize('scope', ['', '0501', '-1', 'S-2-5-18', 'S-1-5', 'S-1-05-18',
    'S-1-5-018', 'S-1-281474976710656-1', 'S-1-5-4294967296', 'S-1-5' + '-1'*16, 'S-1-5-18\n'])
def test_log_user_identity_rejects_invalid_scope(scope):
    vectors = json.loads(VECTORS.read_text())
    event = next(case['event'] for case in vectors if case['valid'])
    event['user_scope'] = scope
    with pytest.raises(ValueError):
        Event.model_validate(event)


def test_batch_rejects_raw_content_duplicate_keys_and_numeric_offsets():
    vectors = json.loads(VECTORS.read_text())
    event = next(case["event"] for case in vectors if case["valid"])
    record = {"sequence": "1", "kind": "event", "record_id": event["logical_event_id"], "payload": event}
    batch = {"schema_version": 1, "records": [record]}
    parsed, events = parse_batch(json.dumps(batch).encode())
    assert len(events) == 1 and parsed.records[0].sequence == "1"
    event["arguments"] = {"password": "synthetic-private-marker"}
    with pytest.raises(ApiError):
        parse_batch(json.dumps(batch).encode())
    with pytest.raises(ApiError):
        parse_batch(b'{"schema_version":1,"schema_version":1,"records":[]}')
    with pytest.raises(ApiError) as error:
        parse_batch(b" " * ((1 << 20) + 1))
    assert error.value.status_code == 413


def test_batch_rejects_repeated_or_unordered_sequence():
    event = next(case["event"] for case in json.loads(VECTORS.read_text()) if case["valid"])
    record = {"sequence": "1", "kind": "event", "record_id": event["logical_event_id"], "payload": event}
    with pytest.raises(ApiError):
        parse_batch(json.dumps({"schema_version": 1, "records": [record, record]}).encode())


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_schema_version_is_integer(version):
    event = next(case["event"] for case in json.loads(VECTORS.read_text()) if case["valid"])
    record = {"sequence": "1", "kind": "event", "record_id": event["logical_event_id"], "payload": event}
    with pytest.raises(ApiError):
        parse_batch(json.dumps({"schema_version": version, "records": [record]}).encode())
    event["schema_version"] = version
    with pytest.raises(ApiError):
        parse_batch(json.dumps({"schema_version": 1, "records": [record]}).encode())


def test_projection_revision_is_optional_for_immutable_old_coverage():
    from backend.aidr_contract import Cursor
    old = dict(schema_version=1, parser_version="agentlog/1", source_id="a"*64,
               file_identity="test", generation="1", discarding_oversized_record=False,
               discard_start="0", offset="0", anchor="b"*64, session_id="", turn_id="",
               agent_version="", since="2026-09-24T00:00:00Z", gap_codes=[])
    assert "projection_version" not in Cursor.model_validate(old).model_dump(exclude_none=True)
    assert Cursor.model_validate({**old, "projection_version": 2}).projection_version == 2
    with pytest.raises(ValueError):
        Cursor.model_validate({**old, "projection_version": 3})


def test_cursor_tool_binding_is_optional_and_bounded():
    from backend.aidr_contract import CallTurn
    old = {"call": "owned-call", "turn": "owned-turn", "ambiguous": False}
    assert CallTurn.model_validate(old).model_dump(exclude_none=True) == old
    assert CallTurn.model_validate(old | {"tool": "exec"}).tool == "exec"
    for tool in ("", "x" * 257, {"password": "synthetic"}, "exec\nraw"):
        with pytest.raises(ValueError):
            CallTurn.model_validate(old | {"tool": tool})
    with pytest.raises(ValueError):
        CallTurn.model_validate(old | {"arguments": {"password": "synthetic"}})


def test_safe_shell_controls_and_quoted_body_boundary():
    from backend.aidr_behavior import Behavior
    base = dict(tool="Bash", category="command", targets=[], source_fields=["command"])
    def validate(command):
        return Behavior.model_validate(dict(version=2, category='command', method='direct_fields', actions=[{**base, 'command':command}], status='unknown', result_basis=[], redacted=False, truncated=False, uncertainty=[]))
    for command in ("/bin/sh -c 'exit 7'", "printf '%s\\n' '[REDACTED]' > ./file"):
        assert validate(command).actions[0].command == command
    with pytest.raises(ValueError):
        validate("printf 'SYNTHETIC_FILE_BODY'")


def test_pending_tool_cursor_capacity_and_legacy_fields():
    from backend.aidr_contract import Cursor, CallTurn, Coverage
    old = dict(schema_version=1, parser_version="agentlog/1", source_id="a" * 64,
               file_identity="test", generation="1", discarding_oversized_record=False,
               discard_start="0", offset="0", anchor="b" * 64, session_id="s", turn_id="t",
               agent_version="0.160.0", since="2026-09-24T00:00:00Z", gap_codes=[])
    bindings = [dict(call=f"c{i}", turn="previous-turn", tool="exec", ambiguous=False,
                     content_digest="c" * 64, completed=i % 2 == 0) for i in range(512)]
    restored = Cursor.model_validate(old | {"call_turns": bindings})
    assert len(restored.call_turns) == 512
    assert restored.call_turns[17].turn == "previous-turn"
    assert restored.call_turns[17].completed is False
    assert Cursor.model_validate(old | {"call_turns": [dict(call="legacy", turn="t", ambiguous=False)]}).call_turns[0].completed is None
    with pytest.raises(ValueError):
        Cursor.model_validate(old | {"call_turns": bindings + [bindings[0]]})
    with pytest.raises(ValueError):
        CallTurn.model_validate(bindings[0] | {"content_digest": "invalid"})
    coverage = dict(gaps=[], gap_details_truncated=False, status="partial",
                    reason_codes=["aidr_log_call_capacity"], records=0, ignored=0,
                    filtered=0, skipped_bytes=0, bytes=0)
    assert Coverage.model_validate(coverage).status == "partial"
    with pytest.raises(ValueError):
        Coverage.model_validate(coverage | {"status": "complete"})


@pytest.mark.parametrize("count", [16, 17])
def test_cli_parallel_calls_merge_into_real_backend_operations(tmp_path, count):
    import subprocess
    from sqlalchemy import create_engine, select
    from backend.aidr_models import AidrOperation
    from backend.aidr_operations import merge_operation
    root = tmp_path.resolve()
    path = root / "parallel.jsonl"
    at = "2026-10-04T10:00:00Z"
    records = [dict(type="session_meta", payload=dict(id="parallel", cli_version="0.160.0")),
               dict(type="turn_context", payload=dict(turn_id="original"))]
    records += [dict(type="response_item", payload=dict(type="function_call", call_id=f"c{i}",
                name="exec_command", arguments={"cmd": "true"})) for i in range(count)]
    records += [dict(type="turn_context", payload=dict(turn_id="later"))]
    records += [dict(type="response_item", payload=dict(type="function_call_output", call_id=f"c{i}",
                output='{"exit_code":0}')) for i in reversed(range(count))]
    path.write_text("".join(json.dumps(dict(timestamp=at, **r)) + "\n" for r in records))
    result = subprocess.run(["go", "run", "./cmd/agent-manager-client", "agent-log-read", "--agent", "codex",
                             "--root", str(root), "--file", str(path), "--since", "2026-10-01T00:00:00Z"],
                            cwd=VECTORS.parents[4], capture_output=True, text=True, check=True)
    batch = json.loads(result.stdout)
    assert batch["coverage"]["status"] == "complete"
    assert len(batch["events"]) == count * 2
    engine = create_engine("sqlite://")
    AidrOperation.__table__.create(engine)
    with engine.begin() as conn:
        for event in batch["events"]:
            validated = Event.model_validate(event)
            assert validated.turn_id == "original"
            merge_operation(conn, "synthetic-device", validated.model_dump(exclude_none=True))
        rows = conn.execute(select(AidrOperation.__table__)).mappings().all()
    assert len(rows) == count
    for row in rows:
        projection = json.loads(row["payload_json"])
        assert projection["call"] and projection["result"]
        assert row["result_status"] == "reported_success"


def test_maximum_tool_cursor_fits_transport_batch():
    from backend.aidr_contract import MAX_BATCH_BYTES
    # Maximum three 256-byte tokens plus digest and completion metadata.
    bindings = [dict(call=str(i).zfill(256), turn="t" * 256, tool="x" * 256,
                     ambiguous=False, completed=False, content_digest="a" * 64)
                for i in range(512)]
    payload = dict(call_turns=bindings)
    serialized = json.dumps(dict(schema_version=1, records=[dict(sequence="1", kind="coverage",
                           record_id="a" * 64 + ":1", payload=payload)])).encode()
    assert len(serialized) < MAX_BATCH_BYTES // 2


def test_recovery_gap_contract_preserves_digest_and_bounds():
    from backend.aidr_contract import CoverageRecord
    cursor = dict(schema_version=1, parser_version="agentlog/1", source_id="a" * 64,
                  file_identity="test", generation="1", discarding_oversized_record=False,
                  discard_start="0", offset="100", anchor="b" * 64, session_id="s", turn_id="t",
                  agent_version="0.160.0", since="2026-09-24T00:00:00Z",
                  gap_codes=["aidr_log_optional_record_skipped"], recovery_details_truncated=False,
                  recovery_gaps=[dict(start="10", end="20", reason_code="aidr_log_optional_record_skipped",
                                      evidence_digest="c" * 64)])
    coverage = dict(gaps=cursor["recovery_gaps"], gap_details_truncated=False, status="partial",
                    reason_codes=cursor["gap_codes"], records=0, ignored=0, filtered=0, skipped_bytes=0, bytes=0)
    payload = dict(source_id="a" * 64, revision="1", cursor=cursor, coverage=coverage)
    result = CoverageRecord.model_validate(payload)
    assert result.cursor.recovery_gaps[0].evidence_digest == "c" * 64
    for changes in ({"end": "101"}, {"evidence_digest": None}, {"evidence_digest": "raw-content"}):
        broken = cursor | {"recovery_gaps": [cursor["recovery_gaps"][0] | changes]}
        with pytest.raises(ValueError):
            CoverageRecord.model_validate(payload | {"cursor": broken})


def test_cli_unknown_optional_record_reaches_following_tool_pair(tmp_path):
    import subprocess
    from backend.aidr_contract import CoverageRecord
    root = tmp_path.resolve()
    path = root / "unknown.jsonl"
    records = [dict(type="session_meta", payload=dict(id="unknown-test", cli_version="0.160.0")),
               dict(type="turn_context", payload=dict(turn_id="known-turn")),
               dict(type="response_item", payload=dict(type="function_call", call_id="before", name="exec_command", arguments={"cmd": "true"})),
               dict(type="event_msg", payload=dict(type="future_optional_telemetry", counter=1)),
               dict(type="response_item", payload=dict(type="function_call_output", call_id="before", output='{"exit_code":0}')),
               dict(type="response_item", payload=dict(type="function_call", call_id="after", name="exec_command", arguments={"cmd": "true"})),
               dict(type="response_item", payload=dict(type="function_call_output", call_id="after", output='{"exit_code":0}'))]
    path.write_text("".join(json.dumps(dict(timestamp="2026-10-04T10:00:00Z", **r)) + "\n" for r in records))
    result = subprocess.run(["go", "run", "./cmd/agent-manager-client", "agent-log-read", "--agent", "codex",
                             "--root", str(root), "--file", str(path), "--since", "2026-10-01T00:00:00Z"],
                            cwd=VECTORS.parents[4], capture_output=True, text=True, check=True)
    batch = json.loads(result.stdout)
    assert len(batch["events"]) == 4
    assert batch["cursor"]["offset"] == str(path.stat().st_size)
    assert batch["coverage"]["status"] == "partial"
    assert batch["coverage"]["reason_codes"] == ["aidr_log_optional_record_skipped"]
    for event in batch["events"]:
        Event.model_validate(event)
        assert event["turn_id"] == "known-turn"
    # The diagnostic CLI includes local repair state; the uploader omits it from wire cursors.
    wire_cursor = {key: value for key, value in batch["cursor"].items()
                   if key not in {"context_repair", "context_repair_version"}}
    CoverageRecord.model_validate(dict(source_id=batch["source"]["source_id"], revision="1",
                                       cursor=wire_cursor, coverage=batch["coverage"]))


@pytest.mark.parametrize("reason", ["host_result_not_provided", "result_format_unsupported", "result_fields_conflict"])
def test_hook_result_uncertainties_require_unknown_projection(reason):
    from backend.aidr_behavior import Behavior
    from backend.aidr_hooks import HookEvent
    behavior = dict(version=1, category="unknown", method="result_fields", actions=[], status="unknown",
                    result_basis=[], redacted=False, truncated=False, uncertainty=[reason])
    result = Behavior.model_validate(behavior)
    assert result.uncertainty == [reason]
    event = dict(schema_version=1, agent="codex", hook_event="PostToolUse", kind="tool.post",
                 session_id="s", turn_id="t", native_call_id="c", tool="Bash", behavior=behavior,
                 policy=dict(version="9", enabled=True, receipt="a" * 32), evidence_digest="b" * 64,
                 process_relation="unknown")
    event["behavior"] = behavior | dict(version=3, policy=event["policy"], body_omitted=True)
    assert HookEvent.model_validate(event).behavior.uncertainty == [reason]
    with pytest.raises(ValueError):
        Behavior.model_validate(behavior | dict(status="reported_success", exit_code=0, result_basis=["structured_exit_code"]))
    with pytest.raises(ValueError):
        Behavior.model_validate(behavior | dict(status="reported_cancelled", result_basis=["interrupted"]))
