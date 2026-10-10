#!/usr/bin/env python3
"""Bounded, privileged real-observer run; generates no model requests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import time


ROOT = Path(__file__).resolve().parent
STOP = False


def stop(_signum, _frame):
    global STOP
    STOP = True


def cpu_seconds(value):
    days = 0
    if "-" in value:
        days, value = value.split("-", 1)
    parts = value.split(":")
    seconds = float(parts[-1])
    for power, component in enumerate(reversed(parts[:-1]), 1):
        seconds += int(component) * 60 ** power
    return int(days) * 86400 + seconds


def resource_report(samples):
    if len(samples) < 2:
        return {"sufficient_samples": False}
    # Discard the first minute from the plateau comparison, but not peak RSS.
    steady = [s for s in samples if s["elapsed_s"] >= 60]
    if len(steady) < 4:
        steady = samples
    quarter = max(1, len(steady) // 4)
    early = statistics.median(s["rss_kib"] for s in steady[:quarter])
    late = statistics.median(s["rss_kib"] for s in steady[-quarter:])
    span = samples[-1]["elapsed_s"] - samples[0]["elapsed_s"]
    cpu = samples[-1]["cpu_seconds"] - samples[0]["cpu_seconds"]
    return {
        "sufficient_samples": True,
        "samples": len(samples),
        "sample_span_s": span,
        "cpu_percent_one_core": 100 * cpu / span if span else 0,
        "peak_rss_mib": max(s["rss_kib"] for s in samples) / 1024,
        "early_median_rss_mib": early / 1024,
        "late_median_rss_mib": late / 1024,
        "rss_growth_mib": (late - early) / 1024,
    }


def sample_processes(monitor_pid, elapsed, cpu_totals):
    result = subprocess.run(["/bin/ps", "-axo", "pid=,ppid=,rss=,time="],
                            capture_output=True, text=True, check=True, timeout=3)
    processes = []
    for line in result.stdout.splitlines():
        pid, ppid, rss, cpu = line.split()
        if int(pid) == monitor_pid or int(ppid) == monitor_pid:
            entry = {"pid": int(pid), "ppid": int(ppid), "rss_kib": int(rss),
                     "cpu_seconds": cpu_seconds(cpu)}
            processes.append(entry)
            cpu_totals[int(pid)] = entry["cpu_seconds"]
    if not any(p["pid"] == monitor_pid for p in processes):
        return None
    return {"elapsed_s": elapsed, "rss_kib": sum(p["rss_kib"] for p in processes),
            "cpu_seconds": sum(cpu_totals.values()), "processes": processes}


def read_events(path, probe_pids):
    count = 0
    last_global = None
    per_type = {}
    sessions = set()
    replayed = 0
    anomalies = []
    probe_exec = {}
    probe_exit = {}
    snapshot = None
    with path.open() as handle:
        for line_number, line in enumerate(handle, 1):
            event = json.loads(line)
            sessions.add(event["monitor_session"])
            if event["event"] == "snapshot_window":
                snapshot = event
                continue
            if event["event"] != "continuous_attribution":
                continue
            count += 1
            replayed += bool(event["replay"])
            current = event["global_seq_num"]
            kind = event["event_type"]
            if last_global is not None and current != last_global + 1:
                anomalies.append({"line": line_number, "reason": "global_sequence"})
            if kind in per_type and event["seq_num"] != per_type[kind] + 1:
                anomalies.append({"line": line_number, "reason": "type_sequence"})
            if event["coverage"] != "complete":
                anomalies.append({"line": line_number, "reason": "degraded"})
            last_global = current
            per_type[kind] = event["seq_num"]
            target = event["target"]
            subject = event["subject"]
            if kind == 2 and target["pid"] in probe_pids and target["path"] == "/usr/bin/true":
                probe_exec[target["pid"]] = event
            if kind == 3 and subject["pid"] in probe_pids:
                probe_exit[subject["pid"]] = event
    identity_keys = ("pid", "pidversion", "start_time_us")
    probes_ok = True
    for pid in probe_pids:
        start, end = probe_exec.get(pid), probe_exit.get(pid)
        if not start or not end:
            probes_ok = False
            continue
        probes_ok &= (
            start["attribution"] == end["attribution"] == "es_confirmed_root"
            and start["root_id"] > 0
            and start["root_id"] == end["root_id"]
            and start["root_identity"] == end["root_identity"]
            and all(start["target"][k] == end["subject"][k] for k in identity_keys)
            and start["global_seq_num"] < end["global_seq_num"]
        )
    return {"events": count, "replayed": replayed, "sessions": sorted(sessions),
            "anomalies": anomalies, "snapshot": snapshot,
            "probes": len(probe_pids), "all_probe_lifecycles_confirmed": bool(probes_ok)}


def check_summary(summary, events):
    failures = []
    if summary["monitor_session"] not in events["sessions"]:
        failures.append("summary_session_mismatch")
    for key in ("gaps", "overflow", "event_discarded", "event_remaining",
                "log_unconfirmed", "log_dropped", "log_errors", "log_remaining"):
        if int(summary[key]) != 0:
            failures.append(key)
    if summary["coverage"] != "complete" or summary["log_shutdown_timeout"] != "false":
        failures.append("observer_degraded")
    for key in ("received", "enqueued", "processed"):
        if int(summary[key]) != events["events"]:
            failures.append("counter_" + key)
    for key in ("log_enqueued", "log_written"):
        if int(summary[key]) != events["events"] + 1:
            failures.append("counter_" + key)
    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=1800)
    parser.add_argument("--interval", type=float, default=5)
    args = parser.parse_args()
    if not 10 <= args.duration <= 3600 or not 1 <= args.interval <= 30:
        parser.error("duration must be 10..3600 seconds; interval 1..30 seconds")
    if os.geteuid() != 0 or not os.environ.get("SUDO_UID"):
        parser.error("run with sudo after building and signing as the normal user")
    uid, gid = int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"])
    work = ROOT / "evidence" / (time.strftime("%Y-%m-%d-stability-%H%M%S") + f"-{os.getpid()}")
    work.mkdir(mode=0o700)
    os.chown(work, uid, gid)
    print(f"evidence directory: {work}", flush=True)
    binary = ROOT / "build/es-continuous-observer"
    metadata = {"duration_s": args.duration, "sample_interval_s": args.interval,
                "observer_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "started_unix": time.time(), "workload": "ambient plus true every 30 seconds",
                "budgets": {"cpu_percent_one_core": 5, "peak_rss_mib": 256,
                            "rss_growth_mib": 16, "max_log_bytes": 512 * 1024 ** 2}}
    (work / "metadata.json").write_text(json.dumps(metadata, indent=2))
    log, error, samples_file = [(work / name).open("w") for name in
                                ("events.jsonl", "observer.stderr", "samples.jsonl")]
    for path in work.iterdir():
        os.chown(path, uid, gid)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)
    monitor = None
    samples, probes, failures = [], [], []
    cpu_totals = {}
    started = time.monotonic()
    forced = False
    try:
        monitor = subprocess.Popen([str(binary), "--ready", str(work / "ready"),
                                    "--duration", str(args.duration), "/usr/bin/true"],
                                   stdout=log, stderr=error, start_new_session=True)
        metadata["monitor_pid"] = monitor.pid
        (work / "metadata.json").write_text(json.dumps(metadata, indent=2))
        next_sample, next_probe, next_progress = 0.0, 0.0, 60.0
        while monitor.poll() is None:
            elapsed = time.monotonic() - started
            if STOP:
                failures.append("interrupted")
                break
            if elapsed > args.duration + 15:
                failures.append("observer_timeout")
                break
            if (work / "events.jsonl").stat().st_size > metadata["budgets"]["max_log_bytes"]:
                failures.append("log_budget")
                break
            if elapsed >= next_sample:
                sample = sample_processes(monitor.pid, elapsed, cpu_totals)
                if sample:
                    sample["log_bytes"] = (work / "events.jsonl").stat().st_size
                    samples.append(sample)
                    samples_file.write(json.dumps(sample) + "\n")
                    samples_file.flush()
                elif monitor.poll() is None:
                    failures.append("resource_sample_failed")
                    break
                next_sample = elapsed + args.interval
            if (work / "ready").exists() and elapsed >= next_probe and elapsed < args.duration - 2:
                probe = subprocess.Popen(["/usr/bin/python3", str(ROOT / "launch_as_user.py"),
                                          str(uid), str(work), "/usr/bin/true"])
                try:
                    if probe.wait(timeout=3) != 0:
                        failures.append("probe_failed")
                    probes.append(probe.pid)
                finally:
                    if probe.poll() is None:
                        probe.kill()
                        probe.wait(timeout=2)
                next_probe = elapsed + 30
            if elapsed >= next_progress:
                print(json.dumps({"elapsed_s": round(elapsed), "samples": len(samples),
                                  "log_mib": round((work / "events.jsonl").stat().st_size / 1024 ** 2, 2)}), flush=True)
                next_progress = elapsed + 60
            time.sleep(0.2)
    except Exception as exc:
        failures.append(type(exc).__name__ + ": " + str(exc))
    finally:
        if monitor and monitor.poll() is None:
            monitor.terminate()
            try:
                monitor.wait(timeout=5)
            except subprocess.TimeoutExpired:
                forced = True
                os.killpg(monitor.pid, signal.SIGKILL)
                monitor.wait(timeout=3)
        log.close()
        error.close()
        samples_file.close()
    elapsed = time.monotonic() - started
    resources = resource_report(samples)
    try:
        events = read_events(work / "events.jsonl", set(probes))
        summary_line = next(line for line in (work / "observer.stderr").read_text().splitlines()
                            if line.startswith("SUMMARY "))
        summary = dict(item.split("=", 1) for item in summary_line.split()[1:] if "=" in item)
        if events["anomalies"] or not events["all_probe_lifecycles_confirmed"] or len(events["sessions"]) != 1:
            failures.append("event_evidence")
        failures.extend(check_summary(summary, events))
    except Exception as exc:
        events, summary = {}, {}
        failures.append("invalid_evidence: " + str(exc))
    if not resources["sufficient_samples"]:
        failures.append("insufficient_samples")
    else:
        if len(samples) < args.duration / args.interval * 0.9:
            failures.append("incomplete_resource_samples")
        for key in ("cpu_percent_one_core", "peak_rss_mib", "rss_growth_mib"):
            if resources[key] > metadata["budgets"][key]:
                failures.append("resource_budget_" + key)
    if not monitor or monitor.returncode != 0 or forced or elapsed < args.duration - 1:
        failures.append("observer_lifecycle")
    if len(probes) != len(set(probes)):
        failures.append("probe_pid_reused_requires_manual_instance_validation")
    if monitor:
        try:
            os.killpg(monitor.pid, 0)
        except ProcessLookupError:
            pass
        else:
            failures.append("observer_process_group_remained")
            os.killpg(monitor.pid, signal.SIGKILL)
    report = {"status": "failed" if failures else ("passed" if args.duration >= 1800 else "smoke_passed"),
              "elapsed_s": elapsed, "returncode": monitor.returncode if monitor else None,
              "forced_kill": forced, "failures": failures, "resources": resources,
              "events": events, "summary": summary, "probe_pids": probes}
    (work / "report.json").write_text(json.dumps(report, indent=2))
    for path in work.iterdir():
        os.chown(path, uid, gid)
    print(json.dumps(report), flush=True)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
