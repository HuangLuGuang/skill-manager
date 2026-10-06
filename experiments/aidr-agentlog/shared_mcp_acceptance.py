"""Owned loopback MCP fixture with one persistent shell, for P3 acceptance.

Only fixed printf probes are executable. This fixture never accepts shell source,
paths or credentials. The standalone check is protocol evidence, not Agent/AIDR
acceptance; native clients can use --serve for subsequent end-to-end checks.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import selectors
import signal
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class SharedProbe:
    def __init__(self, root, barrier_size=0):
        self.root = root
        self.lock = threading.Lock()
        self.sessions = set()
        self.records = []
        self.barrier = threading.Barrier(barrier_size) if barrier_size else None
        self.active = self.peak_active = 0
        self.shell = subprocess.Popen(["/bin/sh"], cwd=root, env={"PATH": "/usr/bin:/bin", "HOME": str(root)},
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    def run(self, session, request_id, arguments):
        if not isinstance(arguments, dict) or set(arguments) != {"slot"} or type(arguments["slot"]) is not int or not 0 <= arguments["slot"] < 20:
            raise ValueError("probe_arguments_invalid")
        with self.lock:
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
        try:
            if self.barrier:
                try:
                    self.barrier.wait(timeout=45)
                except threading.BrokenBarrierError:
                    raise ValueError("probe_concurrency_barrier_timeout") from None
            return self.execute(session, request_id, arguments["slot"])
        finally:
            with self.lock:
                self.active -= 1

    def execute(self, session, request_id, slot):
        with self.lock:
            if session not in self.sessions or len(self.records) >= 100:
                raise ValueError("probe_session_or_budget_invalid")
            # The only variable interpolated into shell source is a bounded int.
            self.shell.stdin.write(f"printf '%s:%s\\n' \"$$\" {slot}\n")
            self.shell.stdin.flush()
            with selectors.DefaultSelector() as poll:
                poll.register(self.shell.stdout, selectors.EVENT_READ)
                if not poll.select(3):
                    raise ValueError("probe_shell_timeout")
            pid, observed = self.shell.stdout.readline().strip().split(":")
            if int(pid) != self.shell.pid or int(observed) != slot:
                raise ValueError("probe_shell_response_mismatch")
            self.records.append({"session": session, "request_id": request_id, "slot": slot,
                                 "server_pid": os.getpid(), "shell_pid": self.shell.pid})
            return {"slot": slot, "shell_pid": self.shell.pid}

    def close(self):
        self.shell.terminate()
        try:
            self.shell.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.shell.kill(); self.shell.wait(timeout=3)
        (self.root / "probe-records.json").write_text(json.dumps(self.records, indent=2))
        (self.root / "probe-concurrency.json").write_text(json.dumps({"peak_inflight": self.peak_active,
            "final_inflight": self.active, "shell_reclaimed": self.shell.poll() is not None}))


def server(root, barrier_size=0):
    probe = SharedProbe(root, barrier_size)
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *_):
            pass
        def reply(self, status, data=None, session=None):
            raw = json.dumps(data).encode() if data is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "close")
            self.close_connection = True
            if session:
                self.send_header("Mcp-Session-Id", session)
            self.end_headers()
            self.wfile.write(raw)
        def do_GET(self):
            self.reply(405)
        def do_POST(self):
            self.connection.settimeout(5)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if self.path != "/mcp" or not 0 < size <= 8192:
                    return self.reply(400)
                message = json.loads(self.rfile.read(size))
                method, params = message["method"], message.get("params", {})
                session = self.headers.get("Mcp-Session-Id")
                if method == "initialize":
                    with probe.lock:
                        if len(probe.sessions) >= 8:
                            return self.reply(429)
                        session = secrets.token_hex(16)
                        probe.sessions.add(session)
                    result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                              "serverInfo": {"name": "aidr-owned-shared-probe", "version": "1"}}
                elif session not in probe.sessions:
                    return self.reply(404)
                elif method == "notifications/initialized":
                    return self.reply(202)
                elif method == "tools/list":
                    result = {"tools": [{"name": "probe", "description": "Run one fixed printf probe in the shared persistent shell.",
                        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
                        "inputSchema": {"type": "object", "properties": {"slot": {"type": "integer", "minimum": 0, "maximum": 19}},
                                        "required": ["slot"], "additionalProperties": False}}]}
                elif method == "tools/call" and params.get("name") == "probe":
                    value = probe.run(session, message["id"], params.get("arguments"))
                    result = {"content": [{"type": "text", "text": json.dumps(value)}], "isError": False}
                else:
                    raise ValueError("probe_method_unsupported")
                self.reply(200, {"jsonrpc": "2.0", "id": message["id"], "result": result}, session)
            except (ValueError, KeyError, TypeError):
                self.reply(400, {"error_code": "probe_invalid_request"})
    class Server(ThreadingHTTPServer):
        request_queue_size = 32  # The acceptance workload opens 20 connections together.
    http = Server(("127.0.0.1", 0), Handler)
    http.daemon_threads = False
    http.block_on_close = True
    return http, probe


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix="aidr-p3-shared-mcp-", dir="/private/tmp"))
    http, probe = server(root)
    thread = threading.Thread(target=http.serve_forever)
    thread.start()
    url = f"http://127.0.0.1:{http.server_port}/mcp"
    (root / "ready.json").write_text(json.dumps({"url": url, "server_pid": os.getpid(), "shell_pid": probe.shell.pid}))
    report = {"scope": "real_shared_MCP_and_shell_protocol_only", "model_calls": 0, "status": "incomplete"}
    def request(method, params, session=None, request_id=1):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if session:
            headers["Mcp-Session-Id"] = session
        raw = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}).encode()
        with urlopen(Request(url, data=raw, headers=headers), timeout=10) as response:
            return response.headers.get("Mcp-Session-Id"), json.load(response)
    try:
        if args.serve:
            print(json.dumps({"ready": str(root / "ready.json")}), flush=True)
            stopped.wait(180)
        else:
            sessions = [request("initialize", {})[0] for _ in range(2)]
            gate = threading.Barrier(20)
            def invoke(slot):
                gate.wait(timeout=10)
                _, response = request("tools/call", {"name": "probe", "arguments": {"slot": slot}},
                                      sessions[slot % 2], request_id=slot // 2)
                value = json.loads(response["result"]["content"][0]["text"])
                assert response["id"] == slot // 2 and value == {"slot": slot, "shell_pid": probe.shell.pid}
            with ThreadPoolExecutor(max_workers=20) as pool:
                list(pool.map(invoke, range(20)))
            try:
                request("tools/call", {"name": "probe", "arguments": {"slot": 0, "command": "not executable"}}, sessions[0])
                raise AssertionError("unknown_input_accepted")
            except HTTPError as error:
                assert error.code == 400
            assert len(probe.records) == 20
            assert len({r["session"] for r in probe.records}) == 2
            assert {r["slot"] for r in probe.records} == set(range(20))
            report.update(status="shared_protocol_isolation_passed", concurrent_requests=20, sessions=2,
                          server_processes=1, persistent_shells=1, unknown_arguments_rejected=True)
    finally:
        http.shutdown(); http.server_close(); thread.join(timeout=5)
        probe.close()
        report["owned_processes_reclaimed"] = not thread.is_alive() and probe.shell.poll() is not None
        (root / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"report": str(root / "report.json"), **report}))


if __name__ == "__main__":
    main()
