"""Bound blocking import preparation separately from ordinary API work."""

import inspect
import os
from functools import partial, wraps

import anyio
from anyio.lowlevel import RunVar


_limiter = RunVar("agent_manager_import_limiter")


def _import_limiter():
    # A limiter belongs to an async runtime, like AnyIO's default thread limiter.
    try:
        return _limiter.get()
    except LookupError:
        try:
            workers = max(1, int(os.environ.get("AGENT_MANAGER_IMPORT_WORKERS", "2")))
        except ValueError:
            workers = 2
        limiter = anyio.CapacityLimiter(workers)
        _limiter.set(limiter)
        return limiter


async def run_import_work(func, *args, **kwargs):
    # Keep cancellation shielded until file handles and temporary directories
    # are released. Waiting for capacity does not borrow ordinary API tokens.
    return await anyio.to_thread.run_sync(partial(func, *args, **kwargs), limiter=_import_limiter())


def import_endpoint(func):
    """Expose a synchronous import handler as an async FastAPI endpoint."""
    @wraps(func)
    async def endpoint(*args, **kwargs):
        return await run_import_work(func, *args, **kwargs)

    # Resolve forward annotations in the original handler's module.
    endpoint.__signature__ = inspect.signature(func, eval_str=True)
    return endpoint
