"""Deterministic contention checks; these thresholds are not production SLAs."""

import asyncio
import io
import sqlite3
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import anyio
import httpx
import pytest
from fastapi import FastAPI

import agent_manager.api.router as api
import agent_manager.api.scanner_router as scanner_api
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import RegistryEntry, SkillStatus, SourceInfo, VettingResult
from agent_manager.core.registry import Registry
from agent_manager.core.runtime import RuntimeGuard
from agent_manager.core.signer import compute_content_digest, compute_signature


def skill_zip():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("SKILL.md", "---\nname: isolation-test\ndescription: test\n---\n")
    return stream.getvalue()


@pytest.mark.parametrize("path,module", [
    ("/skills/submit-zip", api),
    ("/skills/prepare-upload-zip", api),
    ("/skills/prepare-upload-zip?stream=true", api),
    ("/api/v1/scanner/imports", scanner_api),
    ("/skills/submit-url", api),
    ("/skills/prepare-remote-import", api),
    ("/skills/submit-clawhub", api),
])
def test_upload_does_not_block_other_api_requests(tmp_path, monkeypatch, path, module):
    manager = AgentManager(data_dir=tmp_path)
    app = FastAPI()
    app.include_router(api.router)
    app.include_router(scanner_api.router)
    app.dependency_overrides[api.get_manager] = lambda: manager
    app.dependency_overrides[scanner_api.require_scanner_submit_token] = lambda: scanner_api.ScannerAuthContext(
        name="test", max_upload_mb=10,
    )
    app.dependency_overrides[scanner_api.get_token_store] = lambda: SimpleNamespace(log_event=lambda *a, **k: None)
    monkeypatch.setattr(api._scan_executor, "submit", lambda *a, **k: None)
    started, release = threading.Event(), threading.Event()
    extract = module._safe_extract_zip

    def slow_extract(*args, **kwargs):
        started.set()
        release.wait(2)
        return extract(*args, **kwargs)

    monkeypatch.setattr(module, "_safe_extract_zip", slow_extract)
    async_client = httpx.AsyncClient

    def upstream_client(**kwargs):
        return async_client(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, content=skill_zip(), headers={"Content-Type": "application/zip"},
        )), **kwargs)

    monkeypatch.setattr(api.httpx, "AsyncClient", upstream_client)

    async def exercise():
        async with async_client(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            payload = {"json": {"url": "https://example.com/skill.zip"}} if path in {
                "/skills/submit-url", "/skills/prepare-remote-import", "/skills/submit-clawhub",
            } else {"files": {"file": ("skill.zip", skill_zip())}}
            submission = asyncio.create_task(client.post(path, **payload))
            try:
                assert await asyncio.to_thread(started.wait, 3)
                began = time.monotonic()
                response = await client.get("/skills", params={"page": 1, "page_size": 10})
                elapsed = time.monotonic() - began
                assert response.status_code == 200
                # Extraction must still be waiting while the independent API responds.
                assert not submission.done(), f"API loop was stalled by extraction ({elapsed:.3f}s after resuming)"
            finally:
                release.set()
                result = await submission
            assert result.status_code == 200, result.text
            if "stream=true" in path:
                assert '"type": "result"' in result.text

    asyncio.run(exercise())


def test_registry_read_proceeds_during_scan_write(tmp_path):
    registry = Registry(tmp_path)
    entry = RegistryEntry(skill_id="one", name="one", description="test", source=SourceInfo(), status=SkillStatus.APPROVED)
    registry.add(entry)
    started, release = threading.Event(), threading.Event()

    def scan_write():
        with registry._lock, registry._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE skill_registry SET status='REJECTED', payload=json_set(payload, '$.status', 'REJECTED') WHERE skill_id='one'")
            started.set()
            release.wait(2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(scan_write)
        assert started.wait(3)
        try:
            reader = pool.submit(registry.get_by_id, "one")
            assert reader.result(timeout=0.5).status == SkillStatus.APPROVED
            assert not writer.done()
        finally:
            release.set()
            writer.result()
    assert registry.get_by_id("one").status == SkillStatus.REJECTED


def test_import_capacity_does_not_starve_sync_api_threads(monkeypatch):
    from agent_manager.api.import_work import run_import_work

    monkeypatch.setenv("AGENT_MANAGER_IMPORT_WORKERS", "1")
    started, release, second_started = threading.Event(), threading.Event(), threading.Event()

    def slow_import():
        started.set()
        release.wait(3)

    async def exercise():
        # Exhausting the ordinary API capacity used to block unrelated sync routes.
        anyio.to_thread.current_default_thread_limiter().total_tokens = 1
        first = asyncio.create_task(run_import_work(slow_import))
        second = asyncio.create_task(run_import_work(second_started.set))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            assert await asyncio.wait_for(anyio.to_thread.run_sync(lambda: "API responsive"), 0.5) == "API responsive"
            assert not second_started.is_set()
        finally:
            release.set()
            await asyncio.gather(first, second)
        assert second_started.is_set()

    asyncio.run(exercise())


def test_verification_skips_reports_and_observes_revocation(tmp_path, monkeypatch):
    registry = Registry(tmp_path / "registry")
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: signed\ndescription: test\n---\n")
    entry = RegistryEntry(skill_id="signed", name="signed", description="test", source=SourceInfo(),
                          status=SkillStatus.APPROVED, signature=compute_signature(skill), vetting=VettingResult())
    registry.add(entry)
    with registry._connect() as conn:
        conn.execute("INSERT INTO skill_scan_reports VALUES (?, ?, ?)", (entry.skill_id, '{"large":"' + 'x' * 2_000_000 + '"}', "now"))
    statements = []
    connect = registry._connect

    def traced_connect():
        conn = connect()
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(registry, "_connect", traced_connect)
    guard = RuntimeGuard(registry)
    digest = compute_content_digest(skill)
    assert guard.verify_local_signature("signed", digest)[0]
    assert guard.verify_local_signature("signed", digest, skill_id="signed")[0]
    assert guard.can_load("signed")[0]
    assert not any("skill_scan_reports" in sql for sql in statements)
    assert len(registry.read_audit(skill_id="signed")) == 3
    assert len(registry.get_by_id("signed").vetting.scan_report["large"]) == 2_000_000
    entry.status = SkillStatus.RETIRED
    registry.update(entry)
    assert not guard.verify_local_signature("signed", digest)[0]


def test_registry_read_snapshot_is_consistent_and_closed(tmp_path):
    registry = Registry(tmp_path)
    entry = RegistryEntry(skill_id="one", name="one", description="test", source=SourceInfo())
    registry.add(entry)
    with registry._read_connection() as conn:
        before = conn.execute("SELECT status FROM skill_registry WHERE skill_id='one'").fetchone()[0]
        entry.status = SkillStatus.REJECTED
        registry.update(entry)
        assert conn.execute("SELECT status FROM skill_registry WHERE skill_id='one'").fetchone()[0] == before
    assert registry.get_by_id("one").status == SkillStatus.REJECTED
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")


def test_stream_disconnect_waits_for_import_cleanup():
    from agent_manager.api.upload_progress import stream_upload_progress

    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def work(progress):
        started.set()
        try:
            release.wait(2)
            return SimpleNamespace(model_dump=lambda **kwargs: {})
        finally:
            finished.set()

    async def consume():
        async for _ in stream_upload_progress(work).body_iterator:
            pass

    async def exercise():
        async with anyio.create_task_group() as group:
            group.start_soon(consume)
            assert await asyncio.to_thread(started.wait, 1)
            timer = threading.Timer(0.1, release.set)
            timer.start()
            group.cancel_scope.cancel()
        assert finished.is_set()
        timer.join()

    asyncio.run(exercise())


def test_concurrent_imports_reuse_one_pending_version(tmp_path, monkeypatch):
    manager = AgentManager(data_dir=tmp_path)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_manager] = lambda: manager
    scans = []
    monkeypatch.setattr(api._scan_executor, "submit", lambda *args: scans.append(args[2]))
    copytree = api.shutil.copytree

    def slow_snapshot(source, target, *args, **kwargs):
        if "skill_versions" in str(target):
            time.sleep(0.1)
        return copytree(source, target, *args, **kwargs)

    monkeypatch.setattr(api.shutil, "copytree", slow_snapshot)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            results = await asyncio.gather(*(
                client.post("/skills/submit-zip", files={"file": ("skill.zip", skill_zip())}) for _ in range(6)
            ))
        assert all(result.status_code == 200 for result in results)
        ids = {result.json()["version_id"] for result in results}
        assert len(ids) == 1
        assert scans == list(ids)
        assert len(manager.list_scan_runs(scans[0])) == 1

    asyncio.run(exercise())
