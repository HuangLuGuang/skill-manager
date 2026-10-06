#!/usr/bin/env python3
import json, sys
log_path, error_path, fixture_path, claude_path, codex_path = sys.argv[1:6]
parent_pid, child_pid, claude_pid, codex_pid = map(int, sys.argv[6:10])
with open(log_path, encoding="utf-8") as handle: events = [json.loads(line) for line in handle]
with open(error_path, encoding="utf-8") as handle: error_text = handle.read()
sessions = {event.get("monitor_session") for event in events}
assert len(sessions) == 1 and None not in sessions
window = next(event for event in events if event.get("event") == "snapshot_window")
rows = [event for event in events if event.get("event") == "continuous_attribution"]
assert window["begin_mach"] <= window["end_mach"] and window["candidates"] >= 1
assert rows and all(event["message_version"] >= 4 for event in rows)
assert all(event["session_semantics"] == "unknown" and event["tool_semantics"] == "unknown" for event in rows)
globals_ = [event["global_seq_num"] for event in rows]
assert all(right == left + 1 for left, right in zip(globals_, globals_[1:]))
for event_type in (1, 2, 3):
    values = [event["seq_num"] for event in rows if event["event_type"] == event_type]
    assert all(right == left + 1 for left, right in zip(values, values[1:]))
def indices(predicate): return [index for index, event in enumerate(rows) if predicate(event)]
fork = indices(lambda e: e["event_type"] == 1 and e["subject"]["pid"] == parent_pid and e["target"]["pid"] == child_pid and e["parent_link_valid"])
parent_exit = indices(lambda e: e["event_type"] == 3 and e["subject"]["pid"] == parent_pid)
child_exec = indices(lambda e: e["event_type"] == 2 and e["subject"]["pid"] == child_pid and e["target"]["pid"] == child_pid and e["target"]["path"] == "/bin/sleep")
child_exit = indices(lambda e: e["event_type"] == 3 and e["subject"]["pid"] == child_pid)
assert fork and parent_exit and child_exec and child_exit
assert fork[0] < parent_exit[0] < child_exec[0] < child_exit[0]
identity_keys = ("pid", "pidversion", "start_time_us")
def process_identity(value):
    assert value["valid"] and value["pid"] > 0 and value["start_time_us"] > 0
    return tuple(value[key] for key in identity_keys)

assert rows[fork[0]]["subject"]["path"] == fixture_path
assert rows[fork[0]]["mach_time"] > window["end_mach"]
root_id = rows[fork[0]]["root_id"]
for index, expected_kind in ((fork[0], "es_confirmed_descendant"),
                             (parent_exit[0], "es_confirmed_root"),
                             (child_exec[0], "es_confirmed_descendant"),
                             (child_exit[0], "es_confirmed_descendant")):
    event = rows[index]
    assert event["root_id"] == root_id and event["attribution"] == expected_kind
    assert process_identity(event["root_identity"]) == process_identity(rows[fork[0]]["subject"])

assert root_id > 0 and rows[fork[0]]["attribution"] == "es_confirmed_descendant"
assert rows[fork[0]]["subject"] == rows[parent_exit[0]]["subject"]
assert {key: rows[fork[0]]["target"][key] for key in ("pid", "pidversion", "start_time_us")} == {key: rows[child_exec[0]]["subject"][key] for key in ("pid", "pidversion", "start_time_us")}
assert {key: rows[child_exec[0]]["target"][key] for key in ("pid", "pidversion", "start_time_us")} == {key: rows[child_exit[0]]["subject"][key] for key in ("pid", "pidversion", "start_time_us")}
assert rows[child_exec[0]]["root_id"] == root_id and rows[child_exit[0]]["root_id"] == root_id
assert rows[child_exec[0]]["subject"]["pidversion"] != rows[child_exec[0]]["target"]["pidversion"]
for pid, path in ((claude_pid, claude_path), (codex_pid, codex_path)):
    execs = indices(lambda e, pid=pid, path=path: e["event_type"] == 2 and e["target"]["pid"] == pid and e["target"]["path"] == path and e["attribution"] == "es_confirmed_root")
    exits = indices(lambda e, pid=pid: e["event_type"] == 3 and e["subject"]["pid"] == pid)
    assert execs and exits and execs[0] < exits[-1]
    assert rows[execs[0]]["root_id"] == rows[exits[-1]]["root_id"]
    assert rows[execs[0]]["root_identity"] == rows[exits[-1]]["root_identity"]
    assert {key: rows[execs[0]]["target"][key] for key in ("pid", "pidversion", "start_time_us")} == {key: rows[exits[-1]]["subject"][key] for key in ("pid", "pidversion", "start_time_us")}
summary_line = next(line for line in error_text.splitlines() if line.startswith("SUMMARY "))
summary = dict(field.split("=", 1) for field in summary_line.split()[1:] if "=" in field)
assert summary["monitor_session"] in sessions
assert summary["coverage"] == "complete" and summary["gaps"] == "0" and summary["overflow"] == "0"
print(f"PASS session={sessions.pop()} events={len(rows)} candidates={window['candidates']} root_id={root_id}")
