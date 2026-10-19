"""Small retention transactions with cooperative, off-loop backlog draining."""
import asyncio
import logging
from inspect import iscoroutinefunction

from sqlalchemy import inspect, select, tuple_

from .gateway_db import run_sync

BATCH_SIZE = 500


def delete_batch(db, model, predicate, *, limit=BATCH_SIZE, order_by=None):
    keys = inspect(model).primary_key
    selected = select(*keys).where(predicate).order_by(*(order_by or keys)).limit(limit)
    identity = keys[0] if len(keys) == 1 else tuple_(*keys)
    rows = db.execute(selected).all()
    if not rows:
        return 0
    values = [row[0] if len(keys) == 1 else tuple(row) for row in rows]
    # An empty table must not acquire a writer just to discover there is no work.
    # Recheck the predicate in DELETE in case eligibility changed after SELECT.
    return db.query(model).filter(identity.in_(values), predicate).delete(synchronize_session=False)


async def retention_loop(cleanup, name, *, idle_seconds=60, busy_seconds=0.25):
    """cleanup returns whether a bounded pass left work to catch up on."""
    while True:
        try:
            more = await cleanup() if iscoroutinefunction(cleanup) else await run_sync(cleanup)
        except Exception as exc:
            logging.getLogger(__name__).warning('%s retention failed: %s', name, type(exc).__name__)
            more = False
        await asyncio.sleep(busy_seconds if more else idle_seconds)
