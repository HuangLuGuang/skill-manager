#!/usr/bin/env python3
"""Independent real ES -> unprivileged client connection acceptance."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import socket
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parent


def records(path):
    lines = path.read_bytes().splitlines(keepends=True)
    return [json.loads(line) for line in lines if line.endswith(b"\n")]


def wait_for(check, label, timeout=12):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("timeout: " + label)


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
            raise AssertionError("forced termination: " + str(process.pid))


def children(pid):
    output = subprocess.check_output(["/bin/ps", "-axo", "pid=,ppid=,comm="], text=True)
    return [(int(p), name) for line in output.splitlines()
            for p, parent, name in [line.split(None, 2)] if int(parent) == pid]


def main():
    if os.geteuid() != 0 or not os.environ.get("SUDO_UID"):
        raise SystemExit("run with sudo from the test user")
    uid = int(os.environ["SUDO_UID"])
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    account = pwd.getpwuid(uid)
    work = ROOT / "evidence" / (time.strftime("%Y-%m-%d-runtime-connection-%H%M%S-") + str(os.getpid()))
    work.mkdir(mode=0o700)
    secure = Path(tempfile.mkdtemp(prefix="AgentManagerRuntimeTest-", dir="/Library/Application Support"))
    secure.chmod(0o755)
    clients, relays, handles, stopped_observers = [], [], [], set()
    observer_groups = []
    report = {"status": "failed", "checks": [], "client_uid": uid}
    try:
        for source, name in [(ROOT / "build/es-continuous-observer", "observer"),
                             (ROOT / "build/agent-manager-client", "client"),
                             (ROOT / "runtime_observation_relay.py", "relay.py")]:
            target = secure / name
            shutil.copyfile(source, target)
            target.chmod(0o755 if name != "relay.py" else 0o644)
        report["binaries"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in secure.iterdir()}
        socket_path = secure / "runtime.sock"

        insecure = secure / "writable"
        insecure.mkdir(mode=0o777)
        insecure.chmod(0o777)
        rejected = subprocess.run([
            "/usr/bin/python3", "-B", str(secure / "relay.py"),
            "--socket", str(insecure / "bad.sock"), "--allow-uid", str(uid),
            "--observer", str(secure / "observer"),
            "--observer-stderr", str(secure / "rejected.stderr"),
            "--duration", "10", "--catalog", "/usr/bin/true"],
            capture_output=True, text=True, timeout=5)
        assert rejected.returncode != 0 and "runtime_relay_unsafe_path" in rejected.stderr
        assert not (insecure / "bad.sock").exists()
        (work / "unsafe-path.stderr").write_text(rejected.stderr)
        report["checks"].append("writable_ancestor_rejected")

        def launch_relay(index):
            error = (work / f"relay-{index}.stderr").open("w")
            output = (work / f"relay-{index}.stdout").open("w")
            handles.extend([error, output])
            proc = subprocess.Popen([
                "/usr/bin/python3", "-B", str(secure / "relay.py"),
                "--socket", str(socket_path), "--allow-uid", str(uid),
                "--observer", str(secure / "observer"),
                "--observer-stderr", str(secure / f"observer-{index}.stderr"),
                "--duration", "120", "--heartbeat", "1", "--health-timeout", "3",
                "--catalog", "/usr/bin/true"], stdout=output, stderr=error, start_new_session=True)
            relays.append(proc)
            wait_for(lambda: socket_path.exists() or proc.poll() is not None, "socket")
            assert proc.poll() is None, "relay failed: " + (work / f"relay-{index}.stderr").read_text()
            observer_groups.append(wait_for(lambda: next((pid for pid, name in children(proc.pid) if name.endswith("observer")), None), "observer group"))
            return proc

        first = launch_relay(1)
        denied = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        denied.settimeout(3)
        try:
            denied.connect(str(socket_path))
            assert denied.recv(1) == b"", "root peer was not rejected by allow-uid"
        finally:
            denied.close()
        report["checks"].append("unauthorized_root_peer_rejected")
        client_log = work / "client.jsonl"
        output, error = client_log.open("w"), (work / "client.stderr").open("w")
        handles.extend([output, error])
        client = subprocess.Popen([
            "/usr/bin/python3", str(ROOT / "launch_as_user.py"), str(uid), str(secure),
            str(secure / "client"), "runtime-watch", "--socket", str(socket_path),
            "--reconnect", "200ms", "--health-timeout", "4s"], stdout=output, stderr=error)
        clients.append(client)

        def frames():
            return [r["frame"] for r in records(client_log) if r.get("frame")]

        hello = wait_for(lambda: next((f for f in frames() if f["type"] == "hello" and f.get("monitor_session")), None), "hello")
        session1 = hello["monitor_session"]
        assert hello["stream_start"] == "late_join" and hello["attribution_baseline"] == "unknown"
        wait_for(lambda: any(f["type"] == "status" and f.get("observer_health") == "healthy" for f in frames()), "healthy")
        client_uid = subprocess.check_output(["/bin/ps", "-o", "uid=", "-p", str(client.pid)], text=True).strip()
        assert int(client_uid) == uid
        report["checks"].append("nonroot_client_authenticated_and_healthy")

        probe = subprocess.Popen(["/usr/bin/python3", str(ROOT / "launch_as_user.py"), str(uid), str(secure), "/usr/bin/true"])
        assert probe.wait(timeout=3) == 0
        def probe_events():
            events = [f.get("payload", {}) for f in frames() if f["type"] == "event"]
            starts = [e for e in events if e.get("event_type") == 2 and e.get("target", {}).get("pid") == probe.pid and e["target"].get("path") == "/usr/bin/true"]
            ends = [e for e in events if e.get("event_type") == 3 and e.get("subject", {}).get("pid") == probe.pid]
            return (starts[-1], ends[-1]) if starts and ends else None
        start, end = wait_for(probe_events, "probe EXEC/EXIT")
        assert start["root_id"] > 0 and start["root_id"] == end["root_id"]
        assert start["root_identity"] == end["root_identity"]
        assert all(start["target"][k] == end["subject"][k] for k in ("pid", "pidversion", "start_time_us"))
        report["checks"].append("real_probe_identity_and_root")
        observer = wait_for(lambda: next((pid for pid, name in children(first.pid) if name.endswith("observer")), None), "observer pid")
        os.kill(observer, signal.SIGSTOP)
        stopped_observers.add(observer)
        offset = len(records(client_log))
        wait_for(lambda: any(r.get("observer_health") == "stale" or r.get("frame", {}).get("observer_health") == "stale" for r in records(client_log)[offset:]), "observer stale")
        report["checks"].append("stopped_observer_is_not_healthy")
        os.kill(observer, signal.SIGCONT)
        stopped_observers.remove(observer)
        offset = len(records(client_log))
        wait_for(lambda: any(r.get("frame", {}).get("type") == "status" and r["frame"].get("observer_health") == "healthy" for r in records(client_log)[offset:]), "health recovery")
        report["checks"].append("observer_health_recovers")
        offset = len(records(client_log))
        stop(first)
        wait_for(lambda: any(r.get("type") == "client_status" and r.get("transport") == "offline" and r.get("reset") is True for r in records(client_log)[offset:]), "offline reset")
        second = launch_relay(2)
        hello2 = wait_for(lambda: next((r["frame"] for r in records(client_log)[offset:] if r.get("frame", {}).get("type") == "hello" and r["frame"].get("monitor_session") not in (None, "", session1)), None), "new session")
        assert hello2["attribution_baseline"] == "unknown"
        report["sessions"] = [session1, hello2["monitor_session"]]
        report["checks"].append("helper_restart_offline_reset_and_new_session")
        stop(client)
        stop(second)
        assert client.returncode == 0
        report["checks"].append("client_cancellation_exits_zero")
        for pid in [p.pid for p in clients + relays] + observer_groups:
            try:
                os.killpg(pid, 0)
            except ProcessLookupError:
                continue
            raise AssertionError("owned process group remains: " + str(pid))
        report["checks"].append("owned_process_groups_cleaned")
        report["status"] = "passed"
    except BaseException as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        for pid in stopped_observers:
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        for proc in clients + relays:
            try:
                stop(proc)
            except Exception as exc:
                report["status"] = "failed"
                report.setdefault("cleanup_errors", []).append(str(exc))
        for pid in observer_groups:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                continue
            report["status"] = "failed"
            report.setdefault("cleanup_errors", []).append("remaining observer group: " + str(pid))
        for handle in handles:
            handle.close()
        for path in secure.glob("*.stderr"):
            shutil.copyfile(path, work / path.name)
        shutil.rmtree(secure)
        (work / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        for path in work.iterdir():
            os.chown(path, uid, account.pw_gid)
        os.chown(work, uid, account.pw_gid)
    print(json.dumps({"evidence": str(work), **report}, indent=2), flush=True)
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
