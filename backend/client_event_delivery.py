"""Durable identities for the ordinary client events endpoint only."""
import hashlib
import json
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.sqlite import insert

from backend import models
from backend.api_errors import ApiError
from backend.sqlite_db import Base


class ClientEventDelivery(Base):
    __tablename__ = "client_event_deliveries"
    client_id = Column(String(128), primary_key=True)
    delivery_id = Column(String(32), primary_key=True)
    payload_digest = Column(String(64), nullable=False)
    event_id = Column(Integer, ForeignKey("client_events.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def save_delivery(db, client_id, body, observed_at):
    digest = hashlib.sha256(_canonical(body.model_dump(mode="json")).encode()).hexdigest()
    # The first write serializes competing receipts in SQLite. Receipt and event
    # commit together, including requests whose response is subsequently lost.
    created = db.execute(insert(ClientEventDelivery).values(
        client_id=client_id, delivery_id=body.delivery_id, payload_digest=digest,
    ).on_conflict_do_nothing()).rowcount
    receipt = db.query(ClientEventDelivery).filter_by(client_id=client_id, delivery_id=body.delivery_id).one()
    if not created:
        if receipt.payload_digest != digest:
            raise ApiError(409, "client.events_delivery_conflict", "事件确认身份与内容不一致", "Event delivery identity does not match its content")
        return db.query(models.ClientEvent).filter_by(id=receipt.event_id).one(), True

    details = dict(body.details)
    aggregate = (body.event_type in {"skill_governance_recorded", "skill_governance_detected"}
                 and all(isinstance(details.get(k), str) and details[k] for k in
                         ("path", "signature", "policy_version", "trigger", "action", "observation_epoch")))
    key = None
    if aggregate:
        identity_details = {k: v for k, v in details.items() if k not in {
            "observation_count", "last_seen_at", "first_seen_at", "first_seen_source"}}
        identity = [client_id, body.event_type, body.agent_type, body.skill_name, identity_details]
        key = hashlib.sha256(("ordinary-v1:" + _canonical(identity)).encode()).hexdigest()
    row = db.query(models.ClientEvent).filter_by(aggregate_key=key).one_or_none() if key else None
    if row is None:
        row = models.ClientEvent(client_id=client_id, event_type=body.event_type, agent_type=body.agent_type,
                                 skill_name=body.skill_name, details_json=_canonical(details), aggregate_key=key,
                                 observation_count=body.observation_count, last_seen_at=observed_at)
        db.add(row)
        db.flush()
    else:
        old = json.loads(row.details_json)
        row.observation_count = max(row.observation_count, body.observation_count)
        newest = details if row.last_seen_at is None or observed_at >= row.last_seen_at else old
        first = [(v.get("first_seen_at"), v.get("first_seen_source")) for v in (old, details)]
        valid_first = []
        for value, source in first:
            if source not in {"queued_observation", "queue_created_at"} or not isinstance(value, str):
                continue
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is not None:
                valid_first.append((parsed, value, source))
        if valid_first:
            _, newest["first_seen_at"], newest["first_seen_source"] = min(valid_first)
        newest["observation_count"] = row.observation_count
        row.details_json = _canonical(newest)
        row.last_seen_at = max(row.last_seen_at, observed_at) if row.last_seen_at else observed_at
    receipt.event_id = row.id
    return row, False
