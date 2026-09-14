"""Minimal, prompt-free evidence for an explicitly requested native Agent probe."""
import json
import re
from datetime import datetime, timedelta

from . import models

CHALLENGE = re.compile(r"AM_VERIFY_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PARAMETERS = ("stream", "temperature", "top_p", "max_tokens", "max_completion_tokens", "reasoning_effort", "verbosity")


def record_probe(db, key, payload, request_id):
    if not isinstance(key, models.AccessToken) or key.token_type != "agent_runtime" or not key.issued_by_client_token_id:
        return
    text = ""
    for message in reversed(payload.messages):
        if message.role == "user":
            if isinstance(message.content, str):
                text = message.content
            elif isinstance(message.content, list):
                text = " ".join(str(part.get("text", "")) for part in message.content if isinstance(part, dict))
            break
    markers = set(CHALLENGE.findall(text))
    if len(markers) != 1:
        return
    parent = db.get(models.AccessToken, key.issued_by_client_token_id)
    if not parent or not parent.bound_client_id:
        return
    data = payload.model_dump(exclude_none=True)
    details = {"challenge": markers.pop(), "request_id": request_id, "model": payload.model,
               "agent_id": key.bound_agent_id, "credential_id": key.id,
               "parameters": {name: data[name] for name in PARAMETERS if name in data}}
    db.add(models.ClientEvent(client_id=parent.bound_client_id, event_type="model_probe",
                              details_json=json.dumps(details), aggregate_key=request_id))
    db.commit()


def probe_evidence(db, client_id, agent_id, challenge):
    rows = db.query(models.ClientEvent).filter(
        models.ClientEvent.client_id == client_id,
        models.ClientEvent.event_type == "model_probe",
        models.ClientEvent.created_at >= datetime.utcnow() - timedelta(minutes=10),
    ).order_by(models.ClientEvent.id.desc()).limit(100).all()
    result = []
    for event in rows:
        details = json.loads(event.details_json)
        if details.get("challenge") != challenge or details.get("agent_id") != agent_id:
            continue
        audit = db.query(models.LlmRequestAudit).filter_by(
            request_id=details["request_id"], agent_id=agent_id,
            api_key_id=details["credential_id"], credential_type="agent_runtime",
        ).first()
        result.append({"request_id": details["request_id"], "model": details["model"],
                       "parameters": details["parameters"], "status": audit.status if audit else "pending"})
    return result
