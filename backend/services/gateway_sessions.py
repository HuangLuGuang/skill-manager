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
    if explicit_digest:
        group = live_groups.filter(models.GatewaySessionGroup.explicit_digest == explicit_digest).first()
        reason = "explicit_id"
    elif prefixes and any(message.get("role") == "user" for message in messages):
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
    if group is None:
        trace = create_trace(db, tenant_id=tenant_id, agent_id=agent_id,
                             session_id="gws-" + uuid.uuid4().hex,
                             owner_user_id=key.user_id, owner_group_id=key.group_id,
                             created_by="model_gateway", commit=False)
        group = models.GatewaySessionGroup(trace_id=trace.trace_id, scope_id=scope_id,
                                           explicit_digest=explicit_digest,
                                           method="explicit" if explicit_digest else "inferred",
                                           source=source if explicit_digest else "message_history", request_count=0)
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


def finish(db, request_id, status):
    db.query(models.GatewaySessionRequest).filter_by(request_id=request_id, status="running").update(
        {"status": status, "completed_at": datetime.utcnow()}, synchronize_session=False)
    db.commit()


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
