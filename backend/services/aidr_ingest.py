"""Bound collection, audit, projection and retention work before DB workers."""
from contextlib import asynccontextmanager

from anyio import Semaphore
from anyio.lowlevel import RunVar

from .gateway_db import run_db

_slots = RunVar('aidr_bulk_slots')


@asynccontextmanager
async def admission():
    # SQLite has one writer. Queue bulk AIDR work asynchronously within each
    # server event loop; gateway and control-plane requests keep their own path.
    # Cross-process correctness still comes from the database transaction.
    slots = _slots.get(None)
    if slots is None:
        slots = Semaphore(2, max_value=2)
        _slots.set(slots)
    async with slots:
        yield


async def run_ingest(db, function, *args, **kwargs):
    async with admission():
        return await run_db(db, function, *args, **kwargs)
