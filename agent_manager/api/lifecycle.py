"""FastAPI application lifecycle helpers."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI


def lifespan_with_startup(startup: Callable[[], None]):
    """Build a FastAPI lifespan that runs a synchronous startup callback."""

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        startup()
        yield

    return lifespan
