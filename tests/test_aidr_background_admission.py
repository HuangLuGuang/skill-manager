"""Projection and bounded retention share capacity until their worker completes."""
import asyncio
import threading
from types import SimpleNamespace

import pytest

from backend import aidr_overview, aidr_retention, sqlite_db
from backend.services import aidr_ingest


def job(kind, monkeypatch, work):
    if kind == 'projection':
        monkeypatch.setattr(aidr_overview, 'tick', work)
        return aidr_overview.projection_loop()
    def batches(*_, **__):
        work()
        yield 'evidence', 1, False
    monkeypatch.setattr(aidr_retention, '_expire_batches', batches)
    monkeypatch.setattr(sqlite_db, 'SessionLocal', lambda: SimpleNamespace(close=lambda: None))
    return aidr_retention.cleanup_once()


@pytest.mark.parametrize('kind', ['projection', 'retention'])
def test_background_waits_without_starting_database_worker(monkeypatch, kind):
    entered = threading.Event()
    def work():
        entered.set()
        return False
    async def scenario():
        async with aidr_ingest.admission():
            async with aidr_ingest.admission():
                task = asyncio.create_task(job(kind, monkeypatch, work))
                await asyncio.sleep(.03)
                assert not entered.is_set()
            try:
                assert await asyncio.to_thread(entered.wait, 2)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['projection', 'retention'])
def test_cancelled_background_keeps_capacity_until_worker_finishes(monkeypatch, kind):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def work():
        entered.set()
        assert release.wait(5)
        finished.set()
        return False
    async def scenario():
        async with aidr_ingest.admission():
            task = asyncio.create_task(job(kind, monkeypatch, work))
            waiting = None
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                task.cancel()
                async def upload(*_, **__):
                    assert finished.is_set()
                monkeypatch.setattr(aidr_ingest, 'run_db', upload)
                waiting = asyncio.create_task(aidr_ingest.run_ingest(None, None))
                await asyncio.sleep(.03)
                assert not task.done() and not waiting.done()
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
                await asyncio.wait_for(waiting, 2)
            finally:
                release.set()
                await asyncio.gather(task, *([waiting] if waiting else []), return_exceptions=True)
    asyncio.run(scenario())
