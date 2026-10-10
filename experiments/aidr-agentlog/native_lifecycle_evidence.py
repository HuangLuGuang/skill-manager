"""Audit declared hooks against explicitly supplied native-run reports and databases.

Read-only evidence inventory, not a host test. It never reads transcripts or
credentials and never promotes absent events to supported runtime behavior.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3


def inventory(reports, databases, repository):
    observed = {"claude": Counter(), "codex": Counter()}
    runs = []
    seen_streams = set()
    for report_path in reports:
        report_path = Path(report_path).resolve()
        if report_path.stat().st_size > 1024 * 1024:
            raise ValueError("native_report_oversized")
        report = json.loads(report_path.read_text())
        scope = report.get("scope")
        agents = {"native_claude_audit": "claude", "native_claude_compaction_audit": "claude",
                  "native_claude_task_completion_audit": "claude", "native_codex_audit": "codex",
                  "native_claude_subagent_audit": "claude",
                  "native_claude_permission_audit": "claude",
                  "native_claude_interactive_probe": "claude",
                  "native_codex_lifecycle_audit": "codex"}
        if scope not in agents:
            raise ValueError("native_report_scope_unsupported")
        agent = agents[scope]
        health = report.get("final_health")
        if health is None and scope == "native_claude_interactive_probe":
            health = report.get("initial_health")
        stream = health["stream_id"]
        if len(stream) != 32 or any(c not in "0123456789abcdef" for c in stream):
            raise ValueError("native_report_stream_invalid")
        if stream in seen_streams:
            raise ValueError("native_report_stream_duplicate")
        seen_streams.add(stream)
        records = {}
        clients = set()
        for database in databases:
            uri = Path(database).resolve().as_uri() + "?mode=ro"
            with sqlite3.connect(uri, uri=True) as db:
                rows = db.execute(
                    "SELECT client_id, event_id, content_hash, payload_json FROM aidr_hook_events "
                    "WHERE stream_id = ? LIMIT 10001", (stream,)
                ).fetchall()
            if len(rows) > 10000:
                raise ValueError("native_evidence_budget_exceeded")
            for client_id, event_id, digest, payload in rows:
                clients.add(client_id)
                if len(clients) > 1:
                    raise ValueError("native_evidence_device_ambiguous")
                event = json.loads(payload)["event"]
                if event["agent"] != agent:
                    raise ValueError("native_evidence_agent_mismatch")
                value = (digest, event["hook_event"])
                if event_id in records and records[event_id] != value:
                    raise ValueError("native_evidence_conflict")
                records[event_id] = value
        if len(records) != report["received_hooks"]:
            raise ValueError("native_evidence_count_mismatch")
        counts = Counter(value[1] for value in records.values())
        timed_out_interactive = (scope == "native_claude_interactive_probe"
            and report.get("error_type") == "TimeoutExpired" and counts["SessionEnd"] == 1
            and report.get("socket_removed") is True)
        if not records or (report.get("native_exit") != 0 and not timed_out_interactive) or report.get("receiver_exit") != 0:
            raise ValueError("native_run_not_successfully_closed")
        observed[agent].update(counts)
        runs.append({"report": str(report_path), "agent": agent, "stream_id": stream,
                     "client_id": next(iter(clients)),
                     "version": report.get("host_version", report.get("native_version")),
                     "events": dict(sorted(counts.items())), "record_count": len(records),
                     "host_outcome": "timeout_with_session_end_evidence" if timed_out_interactive else "exited_zero",
                     "persistent_trust": report.get("persisted_hook_trust", "not_reported")})
    matrix = {}
    for agent in observed:
        manifest = repository / "client/aidr-plugins" / ("aidr-" + agent) / "hooks/hooks.json"
        declared = json.loads(manifest.read_text())["hooks"]
        if set(observed[agent]) - set(declared):
            raise ValueError("native_event_not_declared")
        matrix[agent] = {hook: {"observed_count": observed[agent][hook],
                               "status": "observed_in_supplied_runs" if observed[agent][hook] else "not_observed"}
                         for hook in declared}
    return {"schema_version": 1, "scope": "explicit_native_run_evidence_inventory",
            "runs": runs, "matrix": matrix,
            "complete_declared_event_observation": all(v["observed_count"] for a in matrix.values() for v in a.values()),
            "limitations": ["No new host execution", "Presence does not prove every payload variant or control behavior",
                            "Persistent trust and OS attribution require separate evidence",
                            "Timed-out interactive runs establish event presence, not successful host completion"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="append", required=True)
    parser.add_argument("--database", action="append", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = inventory(args.report, args.database, Path(__file__).resolve().parents[2])
    with open(args.output, "x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps({"runs": len(result["runs"]), "complete": result["complete_declared_event_observation"]}))


if __name__ == "__main__":
    main()
