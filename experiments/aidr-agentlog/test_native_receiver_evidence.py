"""Receiver diagnostics regressions; no model calls or UI tests."""
import json
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from native_claude_acceptance import receiver_evidence, verify_platform, subagent_result_evidence, subagent_result_matches
from native_claude_interactive_acceptance import resolve_team_model, prompt_for


class ReceiverEvidenceTest(unittest.TestCase):
    def test_interactive_team_model_is_explicit_and_never_guessed(self):
        configured = {"ANTHROPIC_MODEL": "provider-test-model"}
        self.assertEqual(resolve_team_model(configured), "provider-test-model")
        self.assertEqual(resolve_team_model(configured, "other-test-model"), "other-test-model")
        prompt = prompt_for("team", Path("/tmp/owned"), resolve_team_model(configured))
        self.assertIn('model parameter explicitly to sonnet', prompt)
        self.assertIn('maps sonnet to "provider-test-model"', prompt)
        self.assertNotIn('model parameter explicitly to "provider-test-model"', prompt)
        for value in (None, "", "model\nextra instruction", "https://model?token=secret"):
            with self.assertRaisesRegex(ValueError, "interactive_team_requires_explicit_configured_model"):
                resolve_team_model({"ANTHROPIC_MODEL": value})

    def test_subagent_completion_uses_explicit_status_not_missing_error_flag(self):
        row = {"message": {"content": [{"type": "tool_result", "tool_use_id": "call"}]},
            "tool_use_result": {"status": "completed", "agentId": "child", "agentType": "aidr-probe",
                "totalToolUseCount": 0, "content": [{"type": "text", "text": "AIDR-CHILD-DONE"}]}}
        evidence = subagent_result_evidence(row)
        self.assertTrue(subagent_result_matches([{"id": "call"}], [{"id": "call"}], [evidence]))
        for key, value in (("status", None), ("call_id", "other"), ("tool_count", 1), ("is_error", True),
                           ("expected_marker", False), ("agent_id", None)):
            self.assertFalse(subagent_result_matches([{"id": "call"}], [{"id": "call"}], [{**evidence, key: value}]))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "state").mkdir()
        self.database = self.root / "state/hooks.db"
        with sqlite3.connect(self.database) as db:
            db.executescript("CREATE TABLE hook_receipts (id INTEGER); INSERT INTO hook_receipts VALUES (1);"
                             "CREATE TABLE hook_events (id INTEGER); INSERT INTO hook_events VALUES (2),(3);"
                             "CREATE TABLE hook_attempt_reports (acked INTEGER); INSERT INTO hook_attempt_reports VALUES (1),(0);")

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_or_malformed_summary_preserves_readonly_counts(self):
        before = self.database.read_bytes()
        for content in (None, "", "[]", "not-json"):
            if content is not None:
                (self.root / "receiver.json").write_text(content)
            result = receiver_evidence(self.root)
            self.assertEqual((result["acked_hooks"], result["pending_hooks"], result["received_hooks"], result["terminal_reports_acked"]), (1, 2, 3, 1))
            self.assertEqual(result["receiver_diagnostics_code"], "acceptance_receiver_summary_unavailable")
        self.assertEqual(self.database.read_bytes(), before)

    def test_only_stable_codes_leave_summary(self):
        (self.root / "receiver.json").write_text(json.dumps({"upload_code": "aidr_upload_request_rejected",
            "policy_code": "", "control_code": "synthetic secret text", "plugin_code": {"raw": "body"},
            "token": "synthetic-secret"}))
        result = receiver_evidence(self.root)
        self.assertEqual(result["receiver_diagnostics"], {"upload_code": "aidr_upload_request_rejected",
            "policy_code": "", "control_code": "unknown", "plugin_code": "unknown"})
        self.assertNotIn("synthetic", json.dumps(result))

    def test_idle_window_does_not_substitute_for_native_notification(self):
        fixture = self.root / "fixture.json"
        fixture.write_text(json.dumps({"username": "synthetic", "password": "synthetic"}))
        report = {"scope": "native_claude_idle_notification_audit", "session_id": "owned-session",
                  "idle_seconds": 75, "final_health": {"stream_id": "owned-stream", "client_id": "device"}}
        for names, expected in ((["SessionStart", "Stop", "SessionEnd"], False),
                                (["SessionStart", "Notification", "SessionEnd"], True)):
            items = [{"stream_id": "owned-stream", "record": {"event": {
                "hook_event": name, "session_id": "owned-session", "process_relation": "unknown"}}} for name in names]
            # An unrelated stream's notification cannot satisfy this probe.
            items.append({"stream_id": "other-stream", "record": {"event": {"hook_event": "Notification"}}})
            responses = [{"captcha_id": "synthetic"}, {"access_token": "synthetic"},
                         {"items": items, "has_more": False}]
            with patch("native_claude_acceptance.urllib.request.urlopen",
                       side_effect=[io.BytesIO(json.dumps(value).encode()) for value in responses]):
                checks = verify_platform("http://127.0.0.1:1", fixture, report)
            self.assertEqual(checks["native_notification_observed"], expected)
            self.assertTrue(checks["same_owned_session"])

    def test_permission_denial_requires_exact_call_session_and_native_event(self):
        fixture = self.root / "fixture.json"
        fixture.write_text(json.dumps({"username": "synthetic", "password": "synthetic"}))
        for denied_call, denied_session, name, expected in (
            ("call", "owned-session", "PermissionDenied", True),
            ("other-call", "owned-session", "PermissionDenied", False),
            ("call", "other-session", "PermissionDenied", False),
            ("call", "owned-session", "PostToolUseFailure", False)):
            report = {"scope": "native_claude_permission_audit", "session_id": "owned-session",
                "calls": [{"id": "call"}], "final_health": {"stream_id": "owned-stream", "client_id": "device"}}
            events = [{"hook_event": "PreToolUse", "native_call_id": "call", "session_id": "owned-session"},
                      {"hook_event": name, "native_call_id": denied_call, "session_id": denied_session}]
            items = [{"stream_id": "owned-stream", "record": {"event": {**e, "process_relation": "unknown"}}} for e in events]
            items.append({"stream_id": "other-stream", "record": {"event": {"hook_event": "PermissionDenied"}}})
            responses = [{"captcha_id": "synthetic"}, {"access_token": "synthetic"}, {"items": items, "has_more": False}]
            with patch("native_claude_acceptance.urllib.request.urlopen",
                       side_effect=[io.BytesIO(json.dumps(v).encode()) for v in responses]):
                checks = verify_platform("http://127.0.0.1:1", fixture, report)
            self.assertEqual(all(checks.values()), expected)

    def test_subagent_pair_requires_the_same_native_identity(self):
        fixture = self.root / "fixture.json"
        fixture.write_text(json.dumps({"username": "synthetic", "password": "synthetic"}))
        for stop_id, expected in (("child", True), ("other-child", False), (None, False)):
            report = {"scope": "native_claude_subagent_audit", "session_id": "owned-session",
                "calls": [{"id": "call"}], "final_health": {"stream_id": "owned-stream", "client_id": "device"}}
            events = [{"hook_event": "SubagentStart", "native_agent_id": "child"},
                      {"hook_event": "SubagentStop", "native_agent_id": stop_id},
                      {"hook_event": "PreToolUse", "native_call_id": "call"}]
            items = [{"stream_id": "owned-stream", "record": {"event": {
                **e, "session_id": "owned-session", "process_relation": "unknown"}}} for e in events]
            responses = [{"captcha_id": "synthetic"}, {"access_token": "synthetic"}, {"items": items, "has_more": False}]
            with patch("native_claude_acceptance.urllib.request.urlopen",
                       side_effect=[io.BytesIO(json.dumps(v).encode()) for v in responses]):
                checks = verify_platform("http://127.0.0.1:1", fixture, report)
            self.assertEqual(checks["matched_child_lifecycle"], expected)


if __name__ == "__main__":
    unittest.main()
