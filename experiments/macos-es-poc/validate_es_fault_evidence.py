#!/usr/bin/env python3
import json
import sys


def _summary(path):
    with open(path, encoding="utf-8") as handle:
        line = next(line for line in handle if line.startswith("SUMMARY "))
    return dict(field.split("=", 1) for field in line.split()[1:] if "=" in field)


def validate(mode, log_path, error_path, pids_path, status):
    with open(log_path, encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle]
    summary = _summary(error_path)
    with open(pids_path, encoding="utf-8") as handle:
        probe_pids = {int(line) for line in handle}
    snapshot = next(record for record in records
                    if record["event"] == "snapshot_window")
    events = [record for record in records
              if record["event"] == "continuous_attribution"]

    assert snapshot["test_only"] is True and snapshot["test_mode"] == mode
    assert all(event["source"] == "es_notify" for event in events)
    assert int(summary["log_dropped"]) == int(summary["log_errors"]) == 0
    assert int(summary["log_unconfirmed"]) == 0
    assert int(summary["log_remaining"]) == int(summary["event_remaining"]) == 0
    assert int(summary["log_written"]) == len(records)

    if mode == "replay":
        last_global = None
        last_by_type = {}
        for event in events:
            global_sequence = event["global_seq_num"]
            event_type = event["event_type"]
            type_sequence = event["seq_num"]
            if last_global is not None:
                assert global_sequence == last_global + 1
            if event_type in last_by_type:
                assert type_sequence == last_by_type[event_type] + 1
            last_global = global_sequence
            last_by_type[event_type] = type_sequence

        identity_keys = ("pid", "pidversion", "start_time_us")
        for pid in probe_pids:
            executions = [event for event in events
                          if event["event_type"] == 2
                          and event["target"]["pid"] == pid
                          and event["target"]["path"] == "/usr/bin/true"
                          and event["attribution"] == "es_confirmed_root"]
            exits = [event for event in events
                     if event["event_type"] == 3
                     and event["subject"]["pid"] == pid]
            assert len(executions) == len(exits) == 1
            execution, exit_event = executions[0], exits[0]
            assert exit_event["attribution"] == "es_confirmed_root"
            assert execution["root_id"] == exit_event["root_id"] > 0
            assert execution["root_identity"] == exit_event["root_identity"]
            assert all(execution["target"][key] == exit_event["subject"][key]
                       for key in identity_keys)
            assert execution["global_seq_num"] < exit_event["global_seq_num"]

        assert status == 0 and int(summary["overflow"]) == 0
        assert summary["coverage"] == "complete"
        assert any(event["replay"] for event in events)
        assert int(summary["received"]) == int(summary["enqueued"])
        assert int(summary["enqueued"]) == int(summary["processed"])
    else:
        assert status == 74 and int(summary["overflow"]) > 0
        assert int(summary["event_discarded"]) > 0
        assert summary["coverage"] == "degraded"
        assert int(summary["received"]) == (int(summary["enqueued"])
                                               + int(summary["overflow"]))
        assert int(summary["enqueued"]) == (int(summary["processed"])
                                               + int(summary["event_discarded"]))
        assert not any(event["replay"] for event in events)
    return len(events), summary["overflow"]


def main():
    mode, log_path, error_path, pids_path, status_text = sys.argv[1:6]
    events, overflow = validate(mode, log_path, error_path, pids_path,
                                int(status_text))
    print(f"PASS source=real_es_fault mode={mode} status={status_text} "
          f"events={events} overflow={overflow}")


if __name__ == "__main__":
    main()
