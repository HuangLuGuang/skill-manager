"""Standard-library transport and per-process durable delivery."""
import hashlib
import json
import os
import socket
import sqlite3
import threading
import time
import uuid
import inspect
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def dumps(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def fingerprint(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


class Blocked(RuntimeError):
    pass


class ApprovalPause(BaseException):
    """Unwind a node before its first side effect into Dify's checkpoint."""
    def __init__(self, action_id):
        self.action_id = action_id


class Client:
    def __init__(self, config, application):
        self.config = config
        self.app = application
        self.binding = application["binding_id"]
        credentials = json.loads(Path(config["credentials_file"]).read_text())
        self.token = credentials[self.binding]
        self.process_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        root = Path(config["queue_dir"])
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = root / f"{self.binding}.sqlite"
        with self.db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS queue (id TEXT PRIMARY KEY, path TEXT, body TEXT, created REAL)")
            db.execute("CREATE TABLE IF NOT EXISTS approvals (action TEXT PRIMARY KEY, path TEXT, body TEXT, run_id TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)")
            saved_mode = db.execute("SELECT value FROM state WHERE key = 'mode'").fetchone()
        self.path.chmod(0o600)
        self.runs = {}
        self.contexts = {}
        self.lock = threading.Lock()
        self.hooks = {}
        self.mode = saved_mode[0] if saved_mode else application.get("mode", "observe")
        self.resume = None
        threading.Thread(target=self.deliver, daemon=True, name="am-dify-delivery").start()

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def set_mode(self, mode, revision):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            saved = dict(db.execute("SELECT key, value FROM state"))
            if revision >= int(saved.get("revision", "0")):
                db.execute("INSERT OR REPLACE INTO state VALUES ('mode', ?)", (mode,))
                db.execute("INSERT OR REPLACE INTO state VALUES ('revision', ?)", (str(revision),))
                self.mode = mode
            else:
                self.mode = saved["mode"]

    def post(self, path, body):
        request = Request(self.config["server_url"].rstrip("/") + "/api/v1/dify-runtime" + path,
                          data=dumps(body).encode(), headers={"Authorization": "Bearer " + self.token,
                          "Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=5) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            # Never include request headers, parameters or remote response bodies.
            raise Blocked("dify_runtime.platform_unavailable") from None

    def enqueue(self, path, body):
        with self.db() as db:
            if db.execute("SELECT count(*) FROM queue").fetchone()[0] >= 10000:
                raise Blocked("dify_runtime.queue_full")
            db.execute("INSERT INTO queue VALUES (?, ?, ?, ?)", (uuid.uuid4().hex, path, dumps(body), time.time()))

    def deliver(self):
        while True:
            try:
                with self.db() as db:
                    queued = db.execute("SELECT count(*) FROM queue").fetchone()[0]
                    rows = db.execute("SELECT id, path, body FROM queue ORDER BY created LIMIT 100").fetchall()
                health = self.post(f"/bindings/{self.binding}/heartbeat", {
                    "process_id": self.process_id, "dify_version": "1.15.0", "adapter_version": "0.1.0",
                    "hooks": self.hooks, "queued_events": queued})
                self.set_mode(health["mode"], health["revision"])
                for identifier, path, body in rows:
                    if self.post(path, json.loads(body)).get("accepted"):
                        with self.db() as db:
                            db.execute("DELETE FROM queue WHERE id = ?", (identifier,))
                if self.resume:
                    with self.db() as db:
                        pending = db.execute("SELECT action, path, body, run_id FROM approvals").fetchall()
                    for action, path, body, run_id in pending:
                        decision = self.post(path, json.loads(body))
                        if decision["status"] != "pending" and self.resume(run_id, action):
                            with self.db() as db:
                                db.execute("DELETE FROM approvals WHERE action = ?", (action,))
            except Exception as exc:
                logging.getLogger("am_dify_runtime").warning("dify_runtime.delivery_retry.%s", type(exc).__name__)
            time.sleep(5)

    def run(self, context):
        identity = (context["run_id"], context["graph_digest"])
        with self.lock:
            if identity not in self.runs:
                self.runs[identity] = self.post(f"/bindings/{self.binding}/runs", {
                    k: context[k] for k in ("run_id", "workspace_id", "app_id", "workflow_id", "graph_digest")})
                self.set_mode(self.runs[identity]["mode"], self.runs[identity]["revision"])
            return self.runs[identity]

    def observe(self, context, kind, status):
        try:
            self.enqueue(f"/bindings/{self.binding}/observations", {
                "run": {k: context[k] for k in ("run_id", "workspace_id", "app_id", "workflow_id", "graph_digest")},
                "event_id": uuid.uuid4().hex, "event_time": datetime.now(timezone.utc).isoformat(),
                "node_id": context["node_id"], "execution_id": context["execution_id"],
                "node_type": context["node_type"], "type": kind, "status": status})
        except (Blocked, sqlite3.Error):
            if self.mode != "observe":
                raise
            logging.getLogger("am_dify_runtime").error("dify_runtime.observation_lost")

    def execute(self, context, fields, parameters, invoke):
        try:
            run = self.run(context)
        except Blocked:
            if self.mode == "observe":
                return invoke()
            raise
        context["call_index"] = context.get("call_index", 0) + 1
        call_id = fingerprint([context["run_id"], context["execution_id"], context["call_index"]])
        body = {"call_id": call_id, "node_id": context["node_id"],
                "execution_id": context["execution_id"], "node_type": context["node_type"],
                "input_digest": fingerprint(parameters), **fields}
        path = f"/runs/{run['task_id']}/authorize"
        try:
            decision = self.post(path, body)
        except Blocked:
            if self.mode == "observe":
                return invoke()
            raise
        self.set_mode(decision["mode"], decision["revision"])
        if self.mode == "enforce":
            with self.db() as db:
                results = db.execute("SELECT id, path, body FROM queue WHERE path LIKE ? ORDER BY created",
                                     (f"/runs/{run['task_id']}/actions/%/result",)).fetchall()
            for identifier, result_path, result_body in results:
                if not self.post(result_path, json.loads(result_body)).get("accepted"):
                    raise Blocked("dify_runtime.result_unconfirmed")
                with self.db() as db:
                    db.execute("DELETE FROM queue WHERE id = ?", (identifier,))
        if decision["status"] == "pending":
            if context["call_index"] != 1 or context["node_type"] not in {"http-request", "code", "tool", "knowledge-retrieval"}:
                raise Blocked("dify_runtime.approval_checkpoint_unavailable")
            with self.db() as db:
                db.execute("INSERT OR REPLACE INTO approvals VALUES (?, ?, ?, ?)",
                           (decision["action_id"], path, dumps(body), context["run_id"]))
            raise ApprovalPause(decision["action_id"])
        if decision["status"] != "authorized":
            raise Blocked("dify_runtime." + decision["status"])
        action_path = f"/runs/{run['task_id']}/actions/{decision['action_id']}"
        # Reserve durable result space before allowing a side effect.
        with self.db() as db:
            if db.execute("SELECT count(*) FROM queue").fetchone()[0] >= 9900:
                raise Blocked("dify_runtime.queue_full")
        try:
            consumed = self.post(action_path + "/consume", {"authorization_token": decision["authorization_token"],
                                                            "input_digest": body["input_digest"]})
        except Blocked:
            if self.mode == "observe":
                return invoke()
            raise
        if consumed.get("authorized") is not True:
            raise Blocked("dify_runtime.authorization_unconfirmed")
        start = time.monotonic()
        try:
            value = invoke()
        except BaseException:
            self.report_result(action_path, "failed", start)
            raise
        if inspect.isgenerator(value):
            def completed():
                try:
                    yield from value
                except BaseException:
                    self.report_result(action_path, "failed", start)
                    raise
                self.report_result(action_path, "succeeded", start)
            return completed()
        self.report_result(action_path, "failed" if str(getattr(value, "status", "")) == "failed" else "succeeded", start)
        return value

    def report_result(self, path, status, start):
        body = {"status": status, "duration_ms": (time.monotonic()-start)*1000}
        try:
            self.post(path + "/result", body)
        except Blocked:
            self.enqueue(path + "/result", body)
