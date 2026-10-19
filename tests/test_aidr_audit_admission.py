"""Audit catch-up shares upload capacity and releases it after worker completion."""
import asyncio
import threading
from contextlib import asynccontextmanager

import pytest

from backend import aidr_skill_usage as usage
from backend.services import aidr_ingest


def test_released_slot_is_reserved_for_waiter_before_new_admission():
    async def scenario():
        active, peak = 0, 0
        @asynccontextmanager
        async def counted():
            nonlocal active, peak
            async with aidr_ingest.admission():
                active += 1
                peak = max(peak, active)
                try:
                    yield
                finally:
                    active -= 1
        occupied, release = asyncio.Event(), asyncio.Event()
        async def holder():
            async with counted():
                occupied.set()
                await release.wait()
        async def queued():
            async with counted():
                await asyncio.sleep(.02)
        first = asyncio.create_task(holder())
        await occupied.wait()
        try:
            async with counted():
                waiter = asyncio.create_task(queued())
                await asyncio.sleep(.02)
            # Re-enter immediately after waking the queued task, before its
            # continuation runs. The handed-off slot must stay reserved.
            async with counted():
                await asyncio.sleep(.02)
            await waiter
            assert peak == 2
        finally:
            release.set()
            await first
    asyncio.run(scenario())


def test_audit_waits_for_upload_capacity_before_starting_worker(monkeypatch):
    started = threading.Event()
    def maintenance():
        started.set()
        return False
    monkeypatch.setattr(usage, 'maintenance', maintenance)
    async def scenario():
        entered = asyncio.Queue()
        release = asyncio.Event()
        async def blocked(*_, **__):
            await entered.put(True)
            await release.wait()
        monkeypatch.setattr(aidr_ingest, 'run_db', blocked)
        uploads = [asyncio.create_task(aidr_ingest.run_ingest(None, None)) for _ in range(2)]
        await asyncio.wait_for(entered.get(), 2)
        await asyncio.wait_for(entered.get(), 2)
        audit = asyncio.create_task(usage.audit_loop())
        try:
            await asyncio.sleep(.03)
            assert not started.is_set()
            release.set()
            assert await asyncio.to_thread(started.wait, 2)
        finally:
            release.set()
            audit.cancel()
            with pytest.raises(asyncio.CancelledError):
                await audit
            await asyncio.gather(*uploads)
    asyncio.run(scenario())


def test_cancelled_audit_keeps_slot_until_transaction_worker_finishes(monkeypatch):
    started, finish, completed = threading.Event(), threading.Event(), threading.Event()
    def maintenance():
        started.set()
        assert finish.wait(5)
        completed.set()
        return False
    monkeypatch.setattr(usage, 'maintenance', maintenance)
    async def scenario():
        upload_started = asyncio.Event()
        async def upload(*_, **__):
            assert completed.is_set()
            upload_started.set()
        monkeypatch.setattr(aidr_ingest, 'run_db', upload)
        async with aidr_ingest.admission():
            audit = asyncio.create_task(usage.audit_loop())
            try:
                assert await asyncio.to_thread(started.wait, 2)
                audit.cancel()
                waiting = asyncio.create_task(aidr_ingest.run_ingest(None, None))
                await asyncio.sleep(.03)
                assert not audit.done() and not upload_started.is_set()
                finish.set()
                with pytest.raises(asyncio.CancelledError):
                    await audit
                await asyncio.wait_for(waiting, 2)
                assert upload_started.is_set()
            finally:
                finish.set()
                if not audit.done():
                    audit.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await audit
    asyncio.run(scenario())
