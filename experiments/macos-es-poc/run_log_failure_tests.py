#!/usr/bin/env python3
"""Exercise the signed normal observer against real failing output pipes."""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parent


def interrupt_driver(_signum, _frame):
    raise KeyboardInterrupt


def run_case(work, name, interrupt=None):
    folder = work / name
    folder.mkdir()
    ready = folder / "ready"
    process = None
    pipe_read = pipe_write = None
    output = None
    started = time.monotonic()
    try:
        if name in ("blocked_pipe", "broken_pipe"):
            pipe_read, pipe_write = os.pipe()
            if name == "blocked_pipe":
                flags = fcntl.fcntl(pipe_write, fcntl.F_GETFL)
                fcntl.fcntl(pipe_write, fcntl.F_SETFL, flags | os.O_NONBLOCK)
                try:
                    while True:
                        os.write(pipe_write, b"x" * 4096)
                except BlockingIOError:
                    pass
                fcntl.fcntl(pipe_write, fcntl.F_SETFL, flags)
            else:
                os.close(pipe_read)
                pipe_read = None
            sink = pipe_write
        else:
            output = (folder / "events.jsonl").open("w")
            sink = output
        with (folder / "observer.stderr").open("w") as error:
            process = subprocess.Popen([str(ROOT / "build/es-continuous-observer"),
                                        "--ready", str(ready), "--duration", "2" if not interrupt else "60",
                                        "/usr/bin/true"], stdout=sink, stderr=error,
                                       start_new_session=True)
            if pipe_write is not None:
                os.close(pipe_write)
                pipe_write = None
            if interrupt:
                deadline = time.monotonic() + 5
                while not ready.exists() or (folder / "events.jsonl").stat().st_size == 0:
                    assert process.poll() is None, "observer exited before snapshot"
                    assert time.monotonic() < deadline, "snapshot timeout"
                    time.sleep(0.02)
                started = time.monotonic()
                process.send_signal(interrupt)
            exit_code = process.wait(timeout=8)
        elapsed = time.monotonic() - started
        summary_line = next(line for line in (folder / "observer.stderr").read_text().splitlines()
                            if line.startswith("SUMMARY "))
        summary = dict(field.split("=", 1) for field in summary_line.split()[1:] if "=" in field)
        assert elapsed < 8
        assert summary["event_remaining"] == "0"
        if name == "blocked_pipe":
            assert exit_code == 74 and summary["coverage"] == "degraded"
            assert summary["log_shutdown_timeout"] == "true"
            assert int(summary["log_unconfirmed"]) > 0
        elif name == "broken_pipe":
            assert exit_code == 74 and summary["coverage"] == "degraded"
            assert int(summary["log_errors"]) > 0
            assert int(summary["log_unconfirmed"]) > 0
        else:
            assert exit_code == 0 and summary["coverage"] == "complete"
            for key in ("overflow", "log_unconfirmed", "log_dropped", "log_errors", "log_remaining"):
                assert summary[key] == "0", key
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError("owned process group remained")
        return {"case": name, "exit_code": exit_code, "elapsed_s": elapsed,
                "monitor_pid": process.pid, "summary": summary, "process_group_remaining": False}
    finally:
        if process:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if process.poll() is None:
                process.wait(timeout=3)
        for fd in (pipe_read, pipe_write):
            if fd is not None:
                os.close(fd)
        if output:
            output.close()


def main():
    if os.geteuid() != 0 or not os.environ.get("SUDO_UID"):
        raise SystemExit("run with sudo after signing the normal observer")
    signal.signal(signal.SIGTERM, interrupt_driver)
    signal.signal(signal.SIGHUP, interrupt_driver)
    work = Path(tempfile.mkdtemp(prefix="macos-es-log-fault."))
    results = []
    try:
        for name, sig in (("blocked_pipe", None), ("broken_pipe", None),
                          ("interrupt", signal.SIGINT), ("terminate", signal.SIGTERM)):
            result = run_case(work, name, sig)
            results.append(result)
            print(json.dumps(result), flush=True)
    finally:
        (work / "report.json").write_text(json.dumps(results, indent=2))
        uid, gid = int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"])
        for path in [work, *work.rglob("*")]:
            os.chown(path, uid, gid)
        print(f"evidence directory: {work}", flush=True)
    assert len(results) == 4
    print("PASS normal_observer_log_failures_and_signals=verified")


if __name__ == "__main__":
    main()
