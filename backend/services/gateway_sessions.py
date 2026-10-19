"""Credential-scoped, indexed association of model requests with trace sessions."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from sqlalchemy import case, func, update
from sqlalchemy.dialects.sqlite import insert

from .. import models
from .runtime_traces import create_trace


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def history_prefixes(messages):
    """Hash each message once; each prefix commits to the preceding chain."""
    previous = "gateway-history-v1"
    prefixes = []
    for message in messages:
        previous = digest([previous, message])
        prefixes.append(previous)
    return prefixes


def dialogue(messages):
    # Keep message and tool semantics intact; only system/developer context and
    # transport-level null fields are excluded from this additional index.
    return [{k: v for k, v in message.items() if v is not None}
            for message in messages if message.get("role") not in {"system", "developer"}]


def title_exchange(messages):
    if len(messages) != 2 or messages[0].get("role") != "system" or messages[1].get("role") != "user":
        return None
    prompt, content = messages[0].get("content"), messages[1].get("content")
    if not isinstance(prompt, str) or not isinstance(content, str):
        return None
    if not (prompt.startswith("Generate a short, descriptive title (3-7 words) for a conversation")
            and "Return ONLY the title text" in prompt and content.startswith("User: ")):
        return None
    parts = content[6:].split("\n\nAssistant: ")
    if len(parts) != 2 or not all(parts) or any(len(part) > 500 for part in parts):
        return None
    return digest(parts)


def evidence_candidates(db, scope_id, kind, hashes, now):
    matches = []
    for offset in range(0, len(hashes), 400):
        matches.extend(db.query(models.GatewaySessionRequest).join(
            models.GatewaySessionFingerprint,
            models.GatewaySessionFingerprint.request_id == models.GatewaySessionRequest.request_id
        ).join(models.GatewaySessionGroup,
               models.GatewaySessionGroup.trace_id == models.GatewaySessionRequest.trace_id
        ).join(models.RuntimeTraceSession,
               models.RuntimeTraceSession.trace_id == models.GatewaySessionGroup.trace_id
        ).filter(models.GatewaySessionFingerprint.scope_id == scope_id,
                 models.GatewaySessionFingerprint.kind == kind,
                 models.GatewaySessionFingerprint.digest.in_(hashes[offset:offset + 400]),
                 models.RuntimeTraceSession.expires_at > now,
                 models.GatewaySessionGroup.method == "inferred",
                 models.GatewaySessionGroup.source == "message_history").all())
    return matches


def save_fingerprint(db, row, kind, value, count):
    db.merge(models.GatewaySessionFingerprint(request_id=row.request_id, kind=kind,
             scope_id=row.scope_id, digest=value, message_count=count))


def associate(db, *, key, tenant_id, messages, request_id, explicit_id=None, source=None):
    agent_id = key.bound_agent_id if isinstance(key, models.AccessToken) else None
    scope_id = digest([type(key).__name__, key.id, tenant_id, key.user_id, key.group_id, agent_id])
    prefixes = history_prefixes(messages)
    now = datetime.utcnow()
    # SQLite's writer lock covers allocation through commit across processes.
    # Other credentials do no matching work under a Python/global mutex.
    db.execute(insert(models.GatewaySessionScope).values(scope_id=scope_id, updated_at=now)
               .on_conflict_do_nothing(index_elements=["scope_id"]))
    db.execute(update(models.GatewaySessionScope).where(models.GatewaySessionScope.scope_id == scope_id)
               .values(updated_at=now))
    group = None
    matched = None
    reason = "new_history"
    explicit_digest = digest(explicit_id) if explicit_id else None
    live_groups = db.query(models.GatewaySessionGroup).join(
        models.RuntimeTraceSession, models.RuntimeTraceSession.trace_id == models.GatewaySessionGroup.trace_id
    ).filter(models.GatewaySessionGroup.scope_id == scope_id, models.RuntimeTraceSession.expires_at > now)
    probe = db.query(models.ClientEvent.id).filter_by(aggregate_key=request_id, event_type="model_probe").first() is not None
    auxiliary = title_exchange(messages)
    if probe:
        explicit_digest = None
        reason = "connection_probe"
    elif explicit_digest:
        group = live_groups.filter(models.GatewaySessionGroup.explicit_digest == explicit_digest).first()
        reason = "explicit_id"
    elif not auxiliary and prefixes and any(message.get("role") == "user" for message in messages):
        first_user_count = next(i + 1 for i, message in enumerate(messages) if message.get("role") == "user")
        candidates = []
        # Bound SQL parameter counts for long conversations. No history payload reads.
        for offset in range(0, len(prefixes), 400):
            # Aggregate before joining so SQLite cannot choose a trace-wide scan.
            matches = db.query(models.GatewaySessionRequest.trace_id,
                               models.GatewaySessionRequest.message_count,
                               func.min(models.GatewaySessionRequest.request_id).label("request_id")).filter(
                models.GatewaySessionRequest.scope_id == scope_id,
                models.GatewaySessionRequest.message_count >= first_user_count,
                models.GatewaySessionRequest.history_digest.in_(prefixes[offset:offset + 400]),
            ).group_by(models.GatewaySessionRequest.trace_id, models.GatewaySessionRequest.message_count).subquery()
            candidates.extend(db.query(matches).join(
                models.GatewaySessionGroup, models.GatewaySessionGroup.trace_id == matches.c.trace_id
            ).join(models.RuntimeTraceSession,
                   models.RuntimeTraceSession.trace_id == matches.c.trace_id).filter(
                models.GatewaySessionGroup.method == "inferred",
                models.GatewaySessionGroup.source == "message_history",
                models.RuntimeTraceSession.expires_at > now,
            ).all())
        if candidates:
            longest = max(row.message_count for row in candidates)
            best = [row for row in candidates if row.message_count == longest]
            if len({row.trace_id for row in best}) == 1:
                matched = db.get(models.GatewaySessionRequest, best[0].request_id)
                group = db.get(models.GatewaySessionGroup, matched.trace_id)
                reason = "identical_history" if longest == len(messages) else "history_extension"
            else:
                reason = "ambiguous_history"
    if not probe and not explicit_digest and group is None and reason != "ambiguous_history":
        turns = dialogue(messages)
        if auxiliary:
            candidates = evidence_candidates(db, scope_id, "title_exchange_v1", [auxiliary], now)
            matched_reason = "auxiliary_title_v1"
        elif any(item.get("role") == "assistant" for item in turns):
            # Require a previously observed answer, not merely a common first user prompt.
            candidates = evidence_candidates(db, scope_id, "answered_history_v1", history_prefixes(turns), now)
            matched_reason = "dialogue_extension_v1"
        else:
            candidates = []
            matched_reason = "new_history"
        if candidates:
            if len({item.trace_id for item in candidates}) == 1:
                matched = max(candidates, key=lambda item: item.message_count)
                group = db.get(models.GatewaySessionGroup, matched.trace_id)
                reason = matched_reason
            else:
                reason = "ambiguous_history"
    if group is None:
        trace = create_trace(db, tenant_id=tenant_id, agent_id=agent_id,
                             session_id="gws-" + uuid.uuid4().hex,
                             owner_user_id=key.user_id, owner_group_id=key.group_id,
                             created_by="model_gateway", commit=False)
        group = models.GatewaySessionGroup(trace_id=trace.trace_id, scope_id=scope_id,
                                           explicit_digest=explicit_digest,
                                           method="explicit" if explicit_digest else "inferred",
                                           source="connection_probe" if probe else source if explicit_digest else "message_history", request_count=0)
        db.add(group)
    group.request_count += 1
    db.flush()
    db.add(models.GatewaySessionRequest(
        request_id=request_id, trace_id=group.trace_id, scope_id=scope_id,
        history_digest=prefixes[-1] if prefixes else digest([]), message_count=len(messages),
        request_index=group.request_count, match_reason=reason,
        matched_request_id=matched.request_id if matched else None,
        matched_message_count=matched.message_count if matched else 0,
    ))
    trace = db.query(models.RuntimeTraceSession).filter_by(trace_id=group.trace_id).one()
    result = {"gateway_trace_id": trace.trace_id, "session_id": trace.session_id,
              "request_index": group.request_count, "match_reason": reason}
    db.commit()
    return result


def finish(db, request_id, status, request_payload=None, response_payload=None, *, commit=True):
    row = db.get(models.GatewaySessionRequest, request_id)
    if row and status == "completed" and row.match_reason not in {"connection_probe", "auxiliary_title_v1"} and not title_exchange((request_payload or {}).get("messages", [])):
        turns = dialogue((request_payload or {}).get("messages", []))
        choices = (response_payload or {}).get("choices", [])
        if turns and len(choices) == 1:
            choice = choices[0]
            answer = choice.get("message", choice)
            assistant = {"role": "assistant", **{k: v for k, v in answer.items() if k in {"content", "tool_calls"} and v is not None}}
            if len(assistant) > 1:
                complete = turns + [assistant]
                save_fingerprint(db, row, "answered_history_v1", history_prefixes(complete)[-1], len(complete))
            user = next((m.get("content") for m in reversed(turns) if m.get("role") == "user"), None)
            content = assistant.get("content")
            if isinstance(user, str) and user and isinstance(content, str) and content and not assistant.get("tool_calls"):
                save_fingerprint(db, row, "title_exchange_v1", digest([user[:500], content[:500]]), 2)
    db.query(models.GatewaySessionRequest).filter_by(request_id=request_id, status="running").update(
        {"status": status, "completed_at": datetime.utcnow()}, synchronize_session=False)
    if commit:
        db.commit()
    else:
        db.flush()


def summaries(db, trace_ids):
    groups = db.query(models.GatewaySessionGroup).filter(models.GatewaySessionGroup.trace_id.in_(trace_ids)).all()
    statuses = db.query(models.GatewaySessionRequest.trace_id,
                        func.sum(case((models.GatewaySessionRequest.status == "running", 1), else_=0)),
                        func.sum(case((models.GatewaySessionRequest.status.in_(["error", "blocked"]), 1), else_=0)))\
        .filter(models.GatewaySessionRequest.trace_id.in_([row.trace_id for row in groups]))\
        .group_by(models.GatewaySessionRequest.trace_id).all()
    states = {trace_id: "active" if running else "error" if errors else "completed"
              for trace_id, running, errors in statuses}
    return {row.trace_id: {"method": row.method, "source": row.source, "request_count": row.request_count,
                          "status": states.get(row.trace_id, "active")} for row in groups}
