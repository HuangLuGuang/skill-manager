import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor

from agent_manager.core.upload_jobs import UploadImportJobs


def test_persistent_queue_recovers_expired_work_and_retains_partial_results(tmp_path):
    queue = UploadImportJobs(tmp_path, lambda payload, path: {})
    queue.close()
    job = queue.submit({"session_id": "abc", "paths": ["done", "bad", "good"], "filename": "技能合集.zip"})
    with queue.connect() as db:
        db.execute("UPDATE jobs SET status='RUNNING', completed=1, results=?, owner='old', lease=0 WHERE id=?",
                   (json.dumps([{"name": "done"}]), job["job_id"]))
    processed = []
    def process(payload, path):
        processed.append(path)
        if path == "bad":
            raise ValueError("invalid manifest")
        return {"name": path}
    resumed = UploadImportJobs(tmp_path, process)
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = resumed.list()[0]
            if result["status"] == "PARTIAL":
                break
            time.sleep(0.02)
        assert result["filename"] == "技能合集.zip"
        assert result["created_at"] == job["created_at"]
        assert result["status"] == "PARTIAL"
        assert result["completed"] == result["total"] == 3
        assert processed == ["bad", "good"]
        assert result["results"] == [{"name": "done"}, {"name": "good"}]
        assert result["errors"] == [{"path": "bad", "error_code": "upload.import_failed"}]
    finally:
        resumed.close()


def test_concurrent_submission_and_workers_process_one_job_once(tmp_path):
    release = threading.Event()
    entered = threading.Event()
    calls = []
    def process(payload, path):
        calls.append(path)
        entered.set()
        assert release.wait(5)
        return {"name": path}
    first = UploadImportJobs(tmp_path, process)
    second = UploadImportJobs(tmp_path, process)
    try:
        payload = {"session_id": "same", "paths": ["skill"]}
        with ThreadPoolExecutor(max_workers=4) as clients:
            jobs = list(clients.map(lambda _: first.submit(payload), range(8)))
        assert len({job["job_id"] for job in jobs}) == 1
        assert entered.wait(2)
        assert first.active_session("same")
        release.set()
    finally:
        release.set()
        first.close()
        second.close()
    assert calls == ["skill"]
    assert first.list()[0]["status"] == "COMPLETED"
