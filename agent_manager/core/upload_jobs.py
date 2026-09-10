"""Persistent queue for preparing uploaded skills before security scanning."""

import hashlib
import json
import logging
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class UploadImportJobs:
    def __init__(self, data_dir, process_item):
        self.db_path = data_dir / "upload_import_jobs.db"
        self.process_item = process_item
        self.owner = uuid.uuid4().hex
        self.stopped = threading.Event()
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                payload TEXT NOT NULL, status TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0, results TEXT NOT NULL DEFAULT '[]',
                errors TEXT NOT NULL DEFAULT '[]', created REAL NOT NULL,
                owner TEXT, lease REAL NOT NULL DEFAULT 0
            )""")
        self.thread = threading.Thread(target=self.run, name="upload-import-queue", daemon=True)
        self.thread.start()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def public(row):
        payload = json.loads(row["payload"])
        return {"job_id": row["id"], "status": row["status"], "completed": row["completed"],
                "total": len(payload["paths"]), "results": json.loads(row["results"]),
                "errors": json.loads(row["errors"]), "created_at": row["created"],
                "filename": payload.get("filename", "")}

    def submit(self, payload):
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        key = hashlib.sha256(encoded.encode()).hexdigest()
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO jobs (id, request_key, payload, status, created) VALUES (?, ?, ?, 'QUEUED', ?)",
                       (uuid.uuid4().hex, key, encoded, time.time()))
            row = db.execute("SELECT * FROM jobs WHERE request_key = ?", (key,)).fetchone()
        return self.public(row)

    def list(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT 50").fetchall()
        return [self.public(row) for row in rows]

    def active_session(self, session_id):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM jobs WHERE json_extract(payload, '$.session_id') = ? AND status IN ('QUEUED', 'RUNNING') LIMIT 1", (session_id,)).fetchone() is not None

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE status = 'QUEUED' OR (status = 'RUNNING' AND lease < ?) ORDER BY created LIMIT 1", (time.time(),)).fetchone()
            if row:
                db.execute("UPDATE jobs SET status='RUNNING', owner=?, lease=? WHERE id=?", (self.owner, time.time() + 60, row["id"]))
        return row

    def save(self, job_id, status, completed, results, errors):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status=?, completed=?, results=?, errors=? WHERE id=? AND owner=?",
                       (status, completed, json.dumps(results, ensure_ascii=False), json.dumps(errors, ensure_ascii=False), job_id, self.owner))

    def process(self, row):
        payload = json.loads(row["payload"])
        results, errors = json.loads(row["results"]), json.loads(row["errors"])
        completed = row["completed"]
        for path in payload["paths"][completed:]:
            try:
                results.append(self.process_item(payload, path))
            except Exception:
                logger.exception("Upload import item failed for job %s", row["id"])
                errors.append({"path": path, "error_code": "upload.import_failed"})
            completed += 1
            self.save(row["id"], "RUNNING", completed, results, errors)
        status = "COMPLETED" if not errors else "PARTIAL" if results else "FAILED"
        self.save(row["id"], status, completed, results, errors)

    def run(self):
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="upload-import") as executor:
            while not self.stopped.is_set():
                try:
                    row = self.claim()
                    if row is None:
                        self.stopped.wait(0.25)
                        continue
                    future = executor.submit(self.process, row)
                    while True:
                        try:
                            future.result(timeout=5)
                            break
                        except TimeoutError:
                            with self.connect() as db:
                                db.execute("UPDATE jobs SET lease=? WHERE id=? AND owner=?", (time.time() + 60, row["id"], self.owner))
                except Exception:
                    logger.exception("Upload import queue worker failed")
                    self.stopped.wait(1)

    def close(self):
        self.stopped.set()
        self.thread.join()
