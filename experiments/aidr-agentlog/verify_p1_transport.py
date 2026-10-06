"""Real 600-second loopback outage against the production P1 HTTP/Go paths.

Requires p1_server.py on 41873. Owns only its proxy and explicit sync subprocess.
All state, credentials, synthetic raw logs and measurements stay in evidence/.
"""
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--state-dir", required=True)
parser.add_argument("--resume-run", help="verify queries/latency after an already measured completed outage")
args = parser.parse_args()
state = Path(args.state_dir).resolve()
fixture = json.loads((state / "fixture.json").read_text())
run = Path(args.resume_run).resolve() if args.resume_run else state / ("transport-" + str(time.time_ns()))
run.mkdir(mode=0o700, exist_ok=bool(args.resume_run))
for name in ("claude", "codex"):
    (run / name).mkdir(exist_ok=bool(args.resume_run))
marker = run / "offline"
report = {"synthetic": True, "intake_interval_seconds": 2, "max_retry_seconds": 60, "samples": []}
expected = set()
if args.resume_run:
    report = json.loads((run / "report.json").read_text())
    assert report["offline_seconds"] >= 600 and "recovery_seconds" in report
    report["resumed_query_verification"] = True
    expected = {f"p1-{run.name}-{i:05d}" for i in range(10010)}
secret = "SYNTHETIC-PRIVATE-P1-MARKER"

def append(start, count):
    now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    with (run / "claude" / "calls.jsonl").open("a") as f:
        for i in range(start, start + count):
            label = f"p1-{run.name}-{i:05d}"
            expected.add(label)
            f.write(json.dumps({"type": "assistant", "timestamp": now, "sessionId": run.name, "version": "2.1.220", "message": {"content": [{"type": "tool_use", "id": label, "name": "Bash", "input": {"command": secret}}]}}) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return time.monotonic()

def counts():
    with sqlite3.connect(f"file:{run / 'local/state.db'}?mode=ro", uri=True) as db:
        local = db.execute("select count(*) from logical_events").fetchone()[0]
        queued = db.execute("select count(*) from outbox").fetchone()[0]
    with sqlite3.connect(f"file:{state / 'platform.db'}?mode=ro", uri=True) as db:
        remote = db.execute("select count(*) from aidr_events where client_id=?", (fixture["client_id"],)).fetchone()[0]
    return local, queued, remote

def sample():
    values = counts()
    rss = int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(sync.pid)], text=True).strip())
    report["samples"].append({"elapsed": round(time.monotonic()-started, 3), "local": values[0], "queued": values[1], "remote": values[2], "rss_kib": rss, "state_bytes": sum(p.stat().st_size for p in (run / "local").glob("state.db*"))})
    return values

def wait_for(check, timeout):
    end = time.monotonic()+timeout
    while time.monotonic() < end:
        if sync.poll() is not None:
            raise AssertionError("sync exited: " + str(sync.returncode))
        try:
            if check():
                return
        except sqlite3.OperationalError:
            pass
        time.sleep(1)
    raise AssertionError("condition timeout")

def request(path, data=None, token=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(data).encode()
    with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:41873"+path, data=data, headers=headers), timeout=15) as r:
        return json.load(r)

proxy = subprocess.Popen([sys.executable, str(Path(__file__).with_name("p1_network_proxy.py")), "--offline-marker", str(marker)], stdout=subprocess.DEVNULL, stderr=(run / "proxy.log").open("w"))
sync = None
started = time.monotonic()
try:
    time.sleep(1)
    assert proxy.poll() is None
    if not args.resume_run:
        append(0, 10)
    env = dict(os.environ, AGENT_MANAGER_AIDR_TOKEN=(state / "device-token").read_text())
    sync = subprocess.Popen([str(state / "agent-manager-client"), "aidr-sync", "--state-dir", str(run / "local"), "--server", "http://127.0.0.1:41874", "--client-id", fixture["client_id"], "--claude-root", str(run / "claude"), "--codex-root", str(run / "codex")], env=env, stdout=(run / "sync.json").open("w"), stderr=(run / "sync.log").open("w"))
    if not args.resume_run:
        wait_for(lambda: counts()[0] == 10 and counts()[1] == 0, 60)
        baseline = sample()[2]
        marker.touch()
        offline_start = time.monotonic()
        append(10, 10000)
        print(json.dumps({"phase": "offline", "run": str(run), "seconds": 600}), flush=True)
        while time.monotonic()-offline_start < 600:
            time.sleep(min(15, 600-(time.monotonic()-offline_start)))
            values = sample()
            assert values[2] == baseline, "unexpected upload during outage"
            assert sync.poll() is None
        values = sample()
        assert values[0] == 10010 and values[1] >= 10000, values
        report["offline_seconds"] = time.monotonic()-offline_start
        marker.unlink()
        recovered_at = time.monotonic()
        print(json.dumps({"phase": "recovering", "local": values[0], "pending": values[1]}), flush=True)
        wait_for(lambda: counts()[1] == 0 and counts()[2] == baseline+10000, 180)
        report["recovery_seconds"] = time.monotonic()-recovered_at
    sample()
    # Actual authenticated management query, including cursor pagination.
    captcha = request("/api/auth/captcha")
    token = request("/api/auth/token", {"username": fixture["username"], "password": fixture["password"], "captcha_id": captcha["captcha_id"], "captcha_code": "aidr"})["access_token"]
    base = f"/api/v1/clients/{fixture['client_id']}/aidr/events"
    seen, after, pages = set(), "0", 0
    while True:
        page = request(base+"?limit=500&after="+after, token=token)
        encoded = json.dumps(page)
        assert secret not in encoded
        for item in page["items"]:
            seen.add(item["event"]["native_call_id"])
        pages += 1
        after = page["next_after"]
        if not page["has_more"]:
            break
    assert expected <= seen, (len(expected), len(seen))
    report["baseline_plus_offline_unique_calls"] = len(expected)
    report["query_pages"] = pages
    latencies = []
    for i in range(50):
        flushed = append(10010+i, 1)
        target = f"p1-{run.name}-{10010+i:05d}"
        end = flushed+15
        while time.monotonic() < end:
            page = request(base+"?limit=500&after="+after, token=token)
            if any(row["event"]["native_call_id"] == target for row in page["items"]):
                latencies.append(time.monotonic()-flushed)
                after = page["next_after"]
                break
            time.sleep(.2)
        else:
            raise AssertionError("normal network latency timeout")
    report["normal_network_latency_seconds"] = {"samples": len(latencies), "p95": sorted(latencies)[math.ceil(len(latencies)*.95)-1], "max": max(latencies), "query_poll": .2}
    assert report["normal_network_latency_seconds"]["p95"] <= 10
    sample()
    report["passed"] = True
finally:
    if sync and sync.poll() is None:
        sync.send_signal(signal.SIGTERM)
        sync.wait(timeout=20)
    if proxy.poll() is None:
        proxy.terminate()
        proxy.wait(timeout=10)
    report["sync_exit"] = sync.returncode if sync else None
    (run / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"report": str(run / "report.json"), "passed": report.get("passed", False), "sync_exit": report["sync_exit"]}), flush=True)
