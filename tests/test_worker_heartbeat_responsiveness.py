"""A blocked worker heartbeat must leave unrelated HTTP requests responsive."""
import asyncio
import threading
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from backend.routers import security_scans
from backend.sqlite_db import get_db


def test_worker_heartbeat_commit_does_not_block_other_requests():
    entered, release = threading.Event(), threading.Event()
    class Database:
        def commit(self):
            entered.set()
            assert release.wait(3), 'test commit was not released'

    app = FastAPI()
    app.include_router(security_scans.router, prefix='/api')
    app.dependency_overrides[get_db] = lambda: Database()
    app.dependency_overrides[security_scans.resolve_security_worker] = lambda: SimpleNamespace(worker_id='test-worker')

    @app.get('/ping')
    async def ping():
        return {'ok': True}

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            heartbeat = asyncio.create_task(client.post('/api/v1/agent-security/worker/heartbeat'))
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                assert not heartbeat.done()
                response = await asyncio.wait_for(client.get('/ping'), .5)
                assert response.json() == {'ok': True}
            finally:
                release.set()
                response = await heartbeat
            assert response.status_code == 200
            assert response.json()['worker_id'] == 'test-worker'
            assert response.json()['status'] == 'active'
            assert response.json()['server_time']

    asyncio.run(exercise())
