import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "validate_continuous_evidence.py"


def identity(pid, version, start, path):
    return {"pid": pid, "pidversion": version, "start_time_us": start,
            "valid": True, "path": path, "path_complete": True}


class ContinuousEvidenceTests(unittest.TestCase):
    def evidence(self):
        root1 = identity(10, 1, 100, "")
        root2 = identity(20, 2, 200, "")
        root3 = identity(30, 2, 300, "")
        rows = [{"event": "snapshot_window", "monitor_session": "s", "begin_mach": 1,
                 "end_mach": 2, "candidates": 1}]
        specs = [
            (1, 1, identity(10, 1, 100, "/fixture"), identity(11, 1, 110, "/fixture"), "es_confirmed_descendant", 1, root1),
            (3, 2, identity(10, 1, 100, "/fixture"), identity(0, 0, 0, ""), "es_confirmed_root", 1, root1),
            (2, 3, identity(11, 1, 110, "/fixture"), identity(11, 2, 110, "/bin/sleep"), "es_confirmed_descendant", 1, root1),
            (3, 4, identity(11, 2, 110, "/bin/sleep"), identity(0, 0, 0, ""), "es_confirmed_descendant", 1, root1),
            (2, 5, identity(20, 1, 200, "/python"), identity(20, 2, 200, "/claude"), "es_confirmed_root", 2, root2),
            (3, 6, identity(20, 2, 200, "/claude"), identity(0, 0, 0, ""), "es_confirmed_root", 2, root2),
            (2, 7, identity(30, 1, 300, "/python"), identity(30, 2, 300, "/codex"), "es_confirmed_root", 3, root3),
            (3, 8, identity(30, 2, 300, "/codex"), identity(0, 0, 0, ""), "es_confirmed_root", 3, root3),
        ]
        seq = {1: 0, 2: 0, 3: 0}
        for event_type, global_seq, subject, target, attribution, root_id, root in specs:
            seq[event_type] += 1
            rows.append({"event": "continuous_attribution", "monitor_session": "s",
                         "event_type": event_type, "message_version": 4,
                         "global_seq_num": global_seq, "seq_num": seq[event_type], "mach_time": global_seq + 10,
                         "subject": subject, "target": target, "parent_link_valid": True,
                         "attribution": attribution, "root_id": root_id, "root_identity": root,
                         "session_semantics": "unknown", "tool_semantics": "unknown"})
        return rows

    def run_validator(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "events.jsonl"; error = Path(directory) / "stderr"
            log.write_text("".join(json.dumps(row) + "\n" for row in rows))
            error.write_text("SUMMARY monitor_session=s coverage=complete snapshot_coverage=partial epoch=0 gaps=0 overflow=0 reason=\n")
            return subprocess.run(["/usr/bin/python3", str(SCRIPT), str(log), str(error),
                                   "/fixture", "/claude", "/codex", "10", "11", "20", "30"],
                                  capture_output=True)

    def test_valid_evidence(self):
        self.assertEqual(0, self.run_validator(self.evidence()).returncode)

    def test_identity_break_rejected(self):
        rows = self.evidence(); rows[3]["subject"]["pidversion"] = 9
        self.assertNotEqual(0, self.run_validator(rows).returncode)

    def test_wrong_root_identity_rejected(self):
        rows = self.evidence(); rows[3]["root_identity"] = copy.deepcopy(rows[3]["root_identity"])
        rows[3]["root_identity"]["pidversion"] = 99
        self.assertNotEqual(0, self.run_validator(rows).returncode)

    def test_pre_snapshot_fork_rejected(self):
        rows = self.evidence(); rows[1]["mach_time"] = 1
        self.assertNotEqual(0, self.run_validator(rows).returncode)

    def test_global_gap_rejected(self):
        rows = self.evidence(); rows[4]["global_seq_num"] = 9
        self.assertNotEqual(0, self.run_validator(rows).returncode)


if __name__ == "__main__":
    unittest.main()
