"""Read existing local logs, persist only projections into an isolated test DB.

Source path locators and all runtime artifacts remain in ignored evidence/.
This does not interact with managed services or send Agent messages.
"""
import json
import pathlib
import sqlite3
import subprocess
import tempfile
import time

BASE = pathlib.Path(__file__).resolve().parent / "evidence"
BINARY = BASE / "agent-manager-client"
results = []

def run(*args):
    return json.loads(subprocess.check_output([str(BINARY), *args]))

for agent in ("claude", "codex"):
    source = pathlib.Path((BASE / (agent + "-source-path.txt")).read_text().strip())
    scope = ["--agent", agent, "--root", str(source.parent), "--file", str(source),
             "--since", "1970-01-01T00:00:00Z"]
    reference = run("agent-log-read", *scope, "--max-bytes", str(64 << 20),
                    "--max-events", "4096", "--timeout", "30s")
    expected = {event["logical_event_id"] for event in reference["events"]}
    expected_evidence = {event["event_id"] for event in reference["events"]}
    state = pathlib.Path(tempfile.mkdtemp(prefix="store-" + agent + "-", dir=BASE))
    started = time.monotonic()
    rounds = 0
    while rounds < 100:
        result = run("agent-log-collect", "--state-dir", str(state), *scope)
        rounds += 1
        if int(result["checkpoint"]["cursor"]["offset"]) >= int(reference["cursor"]["offset"]):
            break
    else:
        raise AssertionError("collector did not reach reference snapshot")
    persisted = set()
    after = ""
    while True:
        page = run("agent-log-state", "--state-dir", str(state), "--action", "events",
                   "--after", after, "--limit", "137")
        if not page["events"]:
            break
        for event in page["events"]:
            assert event["process_relation"] == "unknown"
            assert event["logical_event_id"] not in persisted
            persisted.add(event["logical_event_id"])
        after = page["next_after"]
    assert expected <= persisted
    status = run("agent-log-state", "--state-dir", str(state))
    assert len(persisted) == status["logical_events"]
    assert status["acknowledged_sequence"] == "0"
    first = run("agent-log-state", "--state-dir", str(state), "--action", "prepare")
    second = run("agent-log-state", "--state-dir", str(state), "--action", "prepare")
    assert first == second  # separate CLI processes, identical durable batch
    assert len(first["payload"]["records"]) <= 500
    integrity = subprocess.check_output([
        "python3", "-c",
        "import sqlite3,sys; print(sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True).execute('pragma integrity_check').fetchone()[0])",
        str(state / "state.db"),
    ], text=True).strip()
    assert integrity == "ok"
    with sqlite3.connect("file:" + str(state / "state.db") + "?mode=ro", uri=True) as db:
        history = [json.loads(row[0]) for row in db.execute("SELECT payload FROM coverage_history")]
        stored_evidence = {row[0] for row in db.execute("SELECT id FROM evidence")}
    assert expected_evidence <= stored_evidence
    skipped = sum(row["coverage"]["skipped_bytes"] for row in history)
    gaps = {}
    for row in history:
        for gap in row["coverage"]["gaps"] or []:
            gaps[gap["start"]] = max(int(gap["end"]), gaps.get(gap["start"], 0))
    assert skipped >= reference["coverage"]["skipped_bytes"]
    results.append({
        "agent": agent, "version": reference["cursor"]["agent_version"],
        "collection_processes": rounds,
        "reference_bytes": int(reference["cursor"]["offset"]),
        "reference_logical_events": len(expected),
        "persisted_logical_events": len(persisted), "status": status,
        "coverage": result["checkpoint"]["coverage"],
        "all_reference_events_persisted": True, "restart_batch_identical": True,
        "all_reference_evidence_persisted": True,
        "integrity_check": integrity,
        "persisted_skipped_bytes": skipped,
        "persisted_gap_ranges": gaps,
        "database_file_bytes": (state / "state.db").stat().st_size,
        "duration_ms": round((time.monotonic() - started) * 1000, 2),
    })

(BASE / "store-live-results.json").write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
