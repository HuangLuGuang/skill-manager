"""Short, serialized database phases for asynchronous gateway requests."""

import asyncio
from functools import partial

from anyio import CancelScope
from sqlalchemy import inspect
from sqlalchemy.orm import InstanceState
from starlette.concurrency import run_in_threadpool


async def run_sync(function, *args, **kwargs):
    """Finish a worker operation before cancellation can start its cleanup."""
    with CancelScope(shield=True):
        task = asyncio.create_task(run_in_threadpool(partial(function, *args, **kwargs)))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # The worker cannot be interrupted safely while it owns a Session/lease.
            # Keep cleanup ordered even when the request task is cancelled repeatedly.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
            task.result()
            raise


async def run_db(db, function, *args, **kwargs):
    """Run one DB phase, returning loaded snapshots with no checked-out connection.

    A request uses its Session sequentially. Commits keep scalar values available
    for the following network phase; close detaches them and returns the connection.
    Each phase must explicitly commit writes it intends to persist.
    """
    def work():
        expire = db.expire_on_commit
        db.expire_on_commit = False
        try:
            result = function(*args, **kwargs)
            state = inspect(result, raiseerr=False)
            # Best-effort last-used writes may roll back and expire a credential.
            # Load the returned snapshot here, before close detaches it.
            if isinstance(state, InstanceState) and state.session is db and state.expired_attributes:
                db.refresh(result)
            return result
        finally:
            db.close()
            db.expire_on_commit = expire

    return await run_sync(work)
