import copy
import json
import tempfile
import unittest
from pathlib import Path

from validate_es_fault_evidence import validate


class FaultEvidenceTests(unittest.TestCase):
    def write_case(self, records, summary, pids=(42,)):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "events").write_text("".join(json.dumps(row) + "\n" for row in records))
        (root / "stderr").write_text("SUMMARY " + " ".join(
            f"{key}={value}" for key, value in summary.items()) + "\n")
        (root / "pids").write_text("".join(f"{pid}\n" for pid in pids))
        return temp, root

    def replay(self):
        identity = {"pid": 42, "pidversion": 7, "start_time_us": 100,
                    "path": "/usr/bin/true"}
        root = dict(identity)
        snapshot = {"event": "snapshot_window", "test_only": True,
                    "test_mode": "replay"}
        launcher = {"event": "continuous_attribution", "source": "es_notify",
                    "event_type": 2, "global_seq_num": 10, "seq_num": 20,
                    "target": {**identity, "path": "/usr/bin/python3"},
                    "subject": identity, "attribution": "unknown", "root_id": 0,
                    "root_identity": {}, "replay": True}
        execution = {"event": "continuous_attribution", "source": "es_notify",
                     "event_type": 2, "global_seq_num": 11, "seq_num": 21,
                     "target": identity, "subject": identity,
                     "attribution": "es_confirmed_root", "root_id": 1,
                     "root_identity": root, "replay": True}
        exit_event = {"event": "continuous_attribution", "source": "es_notify",
                      "event_type": 3, "global_seq_num": 12, "seq_num": 4,
                      "target": {}, "subject": identity,
                      "attribution": "es_confirmed_root", "root_id": 1,
                      "root_identity": root, "replay": True}
        summary = {"log_dropped": 0, "log_errors": 0, "log_unconfirmed": 0,
                   "log_remaining": 0, "event_remaining": 0, "log_written": 4,
                   "overflow": 0, "coverage": "complete", "received": 3,
                   "enqueued": 3, "processed": 3, "event_discarded": 0}
        return [snapshot, launcher, execution, exit_event], summary

    def test_valid_replay(self):
        records, summary = self.replay()
        temp, root = self.write_case(records, summary)
        with temp:
            self.assertEqual((3, "0"), validate("replay", root / "events",
                             root / "stderr", root / "pids", 0))

    def test_wrong_root_rejected(self):
        records, summary = self.replay()
        records[3]["root_identity"] = copy.deepcopy(records[3]["root_identity"])
        records[3]["root_identity"]["pidversion"] = 99
        temp, root = self.write_case(records, summary)
        with temp, self.assertRaises(AssertionError):
            validate("replay", root / "events", root / "stderr", root / "pids", 0)

    def test_missing_log_tail_rejected(self):
        records, summary = self.replay()
        summary["log_written"] = 3
        temp, root = self.write_case(records, summary)
        with temp, self.assertRaises(AssertionError):
            validate("replay", root / "events", root / "stderr", root / "pids", 0)

    def test_fake_overflow_counters_rejected(self):
        records = [{"event": "snapshot_window", "test_only": True,
                    "test_mode": "overflow"}]
        summary = {"log_dropped": 0, "log_errors": 0, "log_unconfirmed": 0,
                   "log_remaining": 0, "event_remaining": 0, "log_written": 1,
                   "overflow": 1, "coverage": "degraded", "received": 5,
                   "enqueued": 3, "processed": 0, "event_discarded": 3}
        temp, root = self.write_case(records, summary, ())
        with temp, self.assertRaises(AssertionError):
            validate("overflow", root / "events", root / "stderr", root / "pids", 74)


if __name__ == "__main__":
    unittest.main()
