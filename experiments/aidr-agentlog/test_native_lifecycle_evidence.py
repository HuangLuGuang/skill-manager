"""Protocol checks for the read-only evidence inventory; no UI or host execution."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from native_lifecycle_evidence import inventory


class EvidenceInventoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.report = self.root / "report.json"
        self.database = self.root / "platform.db"
        self.stream = "a" * 32
        self.report.write_text(json.dumps({"scope": "native_claude_audit", "native_exit": 0,
            "receiver_exit": 0, "received_hooks": 1, "final_health": {"stream_id": self.stream}}))
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE aidr_hook_events (client_id TEXT,stream_id TEXT,event_id TEXT,content_hash TEXT,payload_json TEXT)")
            db.execute("INSERT INTO aidr_hook_events VALUES (?,?,?,?,?)", ("device", self.stream, "event", "digest",
                json.dumps({"event": {"agent": "claude", "hook_event": "SessionStart"}})))
            db.execute("INSERT INTO aidr_hook_events VALUES (?,?,?,?,?)", ("device", "b" * 32, "unrelated", "other",
                json.dumps({"event": {"agent": "codex", "hook_event": "PostToolUse"}})))

    def tearDown(self):
        self.temp.cleanup()

    def run_inventory(self, reports=None, databases=None):
        return inventory(reports or [self.report], databases or [self.database], Path(__file__).resolve().parents[2])

    def test_exact_stream_incomplete_and_duplicate_database_deduplicated(self):
        before = self.database.read_bytes()
        result = self.run_inventory(databases=[self.database, self.database])
        self.assertEqual(result["matrix"]["claude"]["SessionStart"]["observed_count"], 1)
        self.assertEqual(result["matrix"]["codex"]["PostToolUse"]["observed_count"], 0)
        self.assertFalse(result["complete_declared_event_observation"])
        self.assertEqual(before, self.database.read_bytes())

    def test_missing_record_and_duplicate_run_are_not_passes(self):
        with self.assertRaisesRegex(ValueError, "native_report_stream_duplicate"):
            self.run_inventory(reports=[self.report, self.report])
        with sqlite3.connect(self.database) as db:
            db.execute("DELETE FROM aidr_hook_events WHERE stream_id=?", (self.stream,))
        with self.assertRaisesRegex(ValueError, "native_evidence_count_mismatch"):
            self.run_inventory()

    def test_conflicting_copies_are_rejected(self):
        copy = self.root / "copy.db"
        copy.write_bytes(self.database.read_bytes())
        with sqlite3.connect(copy) as db:
            db.execute("UPDATE aidr_hook_events SET content_hash='changed' WHERE stream_id=?", (self.stream,))
        with self.assertRaisesRegex(ValueError, "native_evidence_conflict"):
            self.run_inventory(databases=[self.database, copy])

    def test_same_stream_on_another_device_is_ambiguous(self):
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO aidr_hook_events SELECT 'other-device',stream_id,event_id,content_hash,payload_json FROM aidr_hook_events WHERE stream_id=?", (self.stream,))
        with self.assertRaisesRegex(ValueError, "native_evidence_device_ambiguous"):
            self.run_inventory()

    def test_compaction_observation_requires_matching_agent_records(self):
        report = json.loads(self.report.read_text())
        report["scope"] = "native_claude_compaction_audit"
        self.report.write_text(json.dumps(report))
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE aidr_hook_events SET payload_json=? WHERE stream_id=?", (
                json.dumps({"event": {"agent": "claude", "hook_event": "PreCompact"}}), self.stream))
        result = self.run_inventory()
        self.assertEqual(result["matrix"]["claude"]["PreCompact"]["observed_count"], 1)
        self.assertEqual(result["matrix"]["claude"]["PostCompact"]["observed_count"], 0)
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE aidr_hook_events SET payload_json=? WHERE stream_id=?", (
                json.dumps({"event": {"agent": "codex", "hook_event": "PreCompact"}}), self.stream))
        with self.assertRaisesRegex(ValueError, "native_evidence_agent_mismatch"):
            self.run_inventory()

    def test_task_probe_scope_does_not_invent_completion_event(self):
        report = json.loads(self.report.read_text())
        report["scope"] = "native_claude_task_completion_audit"
        report["status"] = "native_task_completion_passed"
        self.report.write_text(json.dumps(report))
        result = self.run_inventory()
        self.assertEqual(result["matrix"]["claude"]["TaskCompleted"]["observed_count"], 0)
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE aidr_hook_events SET payload_json=? WHERE stream_id=?", (
                json.dumps({"event": {"agent": "claude", "hook_event": "TaskCompleted"}}), self.stream))
        result = self.run_inventory()
        self.assertEqual(result["matrix"]["claude"]["TaskCompleted"]["observed_count"], 1)

    def test_codex_lifecycle_report_cannot_invent_interrupt(self):
        report = json.loads(self.report.read_text())
        report.update(scope="native_codex_lifecycle_audit", status="native_lifecycle_passed")
        self.report.write_text(json.dumps(report))
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE aidr_hook_events SET payload_json=? WHERE stream_id=?", (
                json.dumps({"event": {"agent": "codex", "hook_event": "PreCompact"}}), self.stream))
        result = self.run_inventory()
        self.assertEqual(result["matrix"]["codex"]["PreCompact"]["observed_count"], 1)
        self.assertEqual(result["matrix"]["codex"]["PostCompact"]["observed_count"], 0)
        self.assertEqual(result["matrix"]["codex"]["Interrupt"]["observed_count"], 0)

    def test_permission_report_denial_is_not_invented_from_probe_status(self):
        report = json.loads(self.report.read_text())
        report.update(scope="native_claude_permission_audit", status="native_permission_probe_passed")
        self.report.write_text(json.dumps(report))
        self.assertEqual(self.run_inventory()["matrix"]["claude"]["PermissionDenied"]["observed_count"], 0)
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE aidr_hook_events SET payload_json=? WHERE stream_id=?", (
                json.dumps({"event": {"agent": "claude", "hook_event": "PermissionDenied"}}), self.stream))
        self.assertEqual(self.run_inventory()["matrix"]["claude"]["PermissionDenied"]["observed_count"], 1)

    def test_interactive_timeout_needs_terminal_evidence_and_keeps_timeout_outcome(self):
        report = json.loads(self.report.read_text())
        report.update(scope="native_claude_interactive_probe", native_exit=None,
                      error_type="TimeoutExpired", socket_removed=True)
        report["initial_health"] = report.pop("final_health")
        self.report.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, "native_run_not_successfully_closed"):
            self.run_inventory()
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE aidr_hook_events SET payload_json=? WHERE stream_id=?", (
                json.dumps({"event": {"agent": "claude", "hook_event": "SessionEnd"}}), self.stream))
        result = self.run_inventory()
        self.assertEqual(result["runs"][0]["host_outcome"], "timeout_with_session_end_evidence")
        self.assertEqual(result["matrix"]["claude"]["PermissionDenied"]["observed_count"], 0)
        report["scope"] = "native_claude_audit"
        report["final_health"] = report["initial_health"]
        self.report.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, "native_run_not_successfully_closed"):
            self.run_inventory()


if __name__ == "__main__":
    unittest.main()
