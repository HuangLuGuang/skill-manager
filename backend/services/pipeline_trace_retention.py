"""Expire gateway Pipeline Trace bodies independently of usage/audit records."""
from datetime import datetime

from ..models import LlmPipelineTrace
from .retention import BATCH_SIZE, delete_batch


def cleanup_expired(db, *, now=None, limit=BATCH_SIZE):
    if not 1 <= limit <= BATCH_SIZE:
        raise ValueError('pipeline_trace_retention_budget_invalid')
    deleted = delete_batch(db, LlmPipelineTrace, LlmPipelineTrace.expires_at <= (now or datetime.utcnow()),
                           limit=limit, order_by=(LlmPipelineTrace.expires_at, LlmPipelineTrace.id))
    db.commit()
    return deleted


def cleanup_once():
    from ..sqlite_db import SessionLocal
    with SessionLocal() as db:
        return cleanup_expired(db) == BATCH_SIZE
