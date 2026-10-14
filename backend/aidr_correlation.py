"""Read-only cross-source evidence lookup; never an execution authorization.

Legacy log records lack OS user/subagent provenance. Matching native call keys
can therefore provide an inferred evidence link, not a confirmed process link.
All original events, operation identities and frozen uploads remain unchanged.
"""
from . import aidr_adapters
import json

from sqlalchemy import literal_column, select

from .aidr_models import AidrHookEvent, AidrOperation
from .aidr_enforcement import AidrRuntimeRecord


HOOK_FIELDS = ("agent", "session_id", "turn_id", "native_call_id")


def install_indexes(conn):
    # Literal JSON paths must also be used by queries for SQLite expression
    # indexes to apply. These are fixed product paths, never request input.
    conn.exec_driver_sql("""CREATE INDEX IF NOT EXISTS ix_aidr_hook_native_call
        ON aidr_hook_events(client_id,
        json_extract(payload_json,'$.event.agent'),
        json_extract(payload_json,'$.event.session_id'),
        json_extract(payload_json,'$.event.turn_id'),
        json_extract(payload_json,'$.event.native_call_id'),id)""")
    conn.exec_driver_sql("""CREATE INDEX IF NOT EXISTS ix_aidr_operation_native_call
        ON aidr_operations(client_id,agent,session_id,
        coalesce(json_extract(payload_json,'$.call.turn_id'),json_extract(payload_json,'$.result.turn_id')),
        coalesce(json_extract(payload_json,'$.call.native_call_id'),json_extract(payload_json,'$.result.native_call_id')))""")
    conn.exec_driver_sql("""CREATE INDEX IF NOT EXISTS ix_aidr_hook_session_call
        ON aidr_hook_events(client_id,
        json_extract(payload_json,'$.event.agent'),
        json_extract(payload_json,'$.event.session_id'),
        json_extract(payload_json,'$.event.native_call_id'),id)""")
    conn.exec_driver_sql("""CREATE INDEX IF NOT EXISTS ix_aidr_runtime_process_identity
        ON aidr_runtime_records(client_id,kind,
        json_extract(payload_json,'$.boot_id'),
        json_extract(payload_json,'$.process.pid'),
        json_extract(payload_json,'$.process.pidversion'),
        json_extract(payload_json,'$.process.start_us'),id)""")


def bridge_evidence(db, client_id, record):
    """Historical full-identity match; no tool identity or live authority."""
    peer = record.get("bridge_process")
    result = {"relation": "unknown", "code": "aidr_bridge_not_reported", "items": [], "truncated": False}
    if not peer:
        return result
    result["identity"] = peer
    filters = [AidrRuntimeRecord.client_id == client_id, AidrRuntimeRecord.kind == "process"]
    for path, field in (("boot_id", "boot_id"), ("process.pid", "pid"),
                        ("process.pidversion", "pidversion"), ("process.start_us", "start_us")):
        filters.append(literal_column(f"json_extract(payload_json,'$.{path}')") == peer[field])
    rows = db.execute(select(AidrRuntimeRecord).where(*filters).order_by(AidrRuntimeRecord.id.desc()).limit(5)).scalars().all()
    if not rows:
        result["code"] = "aidr_bridge_no_os_evidence"
        return result
    if len(rows) > 4:
        result.update(code="aidr_bridge_evidence_budget", truncated=True)
        return result
    roots = set()
    for row in rows:
        payload = json.loads(row.payload_json)
        root = payload.get("root")
        if root and payload.get("relation") in ("direct", "inherited"):
            roots.add(json.dumps(root, sort_keys=True))
        result["items"].append({"id": str(row.id), "monitor_id": row.monitor_id,
            "sequence": row.sequence, "time_ns": payload["time_ns"],
            "transition": payload.get("transition", ""), "relation": payload.get("relation", "unknown"),
            "root": root})
    result.update(relation="matched", code="aidr_bridge_identity_matched")
    if len(roots) > 1:
        result.update(relation="conflicting", code="aidr_bridge_roots_conflict")
    return result


def operation_identity_filter(client_id, event):
    filters = [
        AidrOperation.client_id == client_id,
        AidrOperation.agent == event["agent"],
        AidrOperation.session_id == event["session_id"],
        literal_column("coalesce(json_extract(payload_json,'$.call.native_call_id'),json_extract(payload_json,'$.result.native_call_id'))") == event["native_call_id"],
    ]
    if not aidr_adapters.get(event["agent"]).session_call_identity or event["turn_id"]:
        filters.append(literal_column("coalesce(json_extract(payload_json,'$.call.turn_id'),json_extract(payload_json,'$.result.turn_id'))") == event["turn_id"])
    return filters


def hook_evidence(db, client_id, operation):
    result = {"relation": "unknown", "code": "aidr_link_identity_missing", "items": [],
              "process_relation": "unknown", "truncated": False}
    event = operation.get("call") or operation.get("result")
    if not event or not event.get("session_id") or not event.get("native_call_id") or (aidr_adapters.get(event["agent"]).turn_required and not event.get("turn_id")):
        return result
    if operation.get("conflicting_evidence") or operation.get("evidence_truncated"):
        result["code"] = "aidr_link_log_conflict"
        return result
    # Two log sources claiming one native identity cannot be silently merged.
    peers = db.execute(select(AidrOperation.id).where(*operation_identity_filter(client_id, event)).limit(2)).all()
    if len(peers) != 1:
        result["code"] = "aidr_link_source_ambiguous"
        return result
    filters = [AidrHookEvent.client_id == client_id]
    # Claude's tool-use ID is session-scoped; current logs omit the prompt ID
    # supplied by hooks. Codex call IDs require the turn namespace.
    fields = [field for field in HOOK_FIELDS if field != "turn_id" or not aidr_adapters.get(event["agent"]).session_call_identity or event.get("turn_id")]
    filters.extend(literal_column(f"json_extract(payload_json,'$.event.{field}')") == event.get(field, "") for field in fields)
    rows = db.execute(select(AidrHookEvent).where(*filters).order_by(AidrHookEvent.id).limit(17)).scalars().all()
    if not rows:
        result["code"] = "aidr_link_no_matching_hook"
        return result
    if len(rows) > 16:
        result.update(code="aidr_link_evidence_budget", truncated=True)
        return result
    records = [json.loads(row.payload_json) for row in rows]
    # Receiver streams are not user identities. Multiple users or subagent
    # namespaces require provenance absent from legacy logs, even with one call ID.
    users = {record.get("user_scope", "") for record in records}
    turns = {record["event"].get("turn_id", "") for record in records}
    if len(users) != 1 or "" in users or len(turns) != 1 or any(record["event"].get("native_agent_id") for record in records):
        result["code"] = "aidr_link_source_ambiguous"
        return result
    tool = (operation.get("call") or {}).get("tool")
    if not tool or any(record["event"].get("tool") != tool for record in records):
        result["code"] = "aidr_link_tool_unverified"
        return result
    summaries = []
    for row, record in zip(rows, records):
        hook = record["event"]
        behavior = hook.get("behavior") or {}
        summaries.append({"id": str(row.id), "stream_id": row.stream_id,
            "event_id": record["event_id"], "hook_event": hook["hook_event"],
            "received_at": record["received_at"], "user_scope": record["user_scope"],
            "status": behavior.get("status", "unknown"), "exit_code": behavior.get("exit_code"),
            "result_basis": behavior.get("result_basis", []),
            "bridge_evidence": bridge_evidence(db, client_id, record)})
    if len(json.dumps(summaries).encode()) > 8192:
        result.update(code="aidr_link_evidence_budget", truncated=True)
        return result
    result.update(relation="inferred", code="aidr_link_native_identity_user_unverified", items=summaries)
    return result
