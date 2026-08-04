import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import auth, models
from ..security_audit import verify_security_audit
from ..sqlite_db import get_db


router = APIRouter(prefix="/v1/security-audit", tags=["security-audit"])


@router.get("/events")
async def list_security_audit_events(
    limit: int = 100,
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(auth.get_current_admin_user),
):
    rows = db.query(models.SecurityAuditEvent).order_by(models.SecurityAuditEvent.id.desc()).limit(min(max(limit, 1), 500)).all()
    return [{
        "event_id": row.event_id,
        "timestamp": row.timestamp,
        "event_type": row.event_type,
        "actor": row.actor,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "action": row.action,
        "outcome": row.outcome,
        "details": json.loads(row.details_json or "{}"),
        "prev_hash": row.prev_hash,
        "event_hash": row.event_hash,
        "key_id": row.key_id,
        "signature": row.signature,
    } for row in rows]


@router.get("/verify")
async def verify_security_audit_chain(
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(auth.get_current_admin_user),
):
    return verify_security_audit(bind=db.get_bind())
