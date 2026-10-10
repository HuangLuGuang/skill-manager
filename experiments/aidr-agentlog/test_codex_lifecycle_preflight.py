"""Native probe trust/profile boundaries; does not run a model or UI."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from native_codex_lifecycle_acceptance import approval_matches, inventory_trusted, owned_profile


class PreflightTest(unittest.TestCase):
    def test_approval_requires_exact_owned_thread_turn_command_and_directory(self):
        work = Path('/private/tmp/owned/work'); marker = work / 'denied-marker'
        report = {"session_id": "owned-thread", "permission_turn_id": "owned-turn"}
        params = {"threadId": "owned-thread", "turnId": "owned-turn", "itemId": "owned-item",
                  "cwd": str(work), "command": f'/usr/bin/touch "{marker}"'}
        self.assertTrue(approval_matches(params, report, work, marker))
        self.assertTrue(approval_matches({**params, "command": f"/bin/zsh -c '/usr/bin/touch {marker}'"}, report, work, marker))
        self.assertFalse(approval_matches({**params, "command": f"/bin/zsh -c '/usr/bin/touch {marker} && pwd'"}, report, work, marker))
        for key, value in (("threadId", "other"), ("turnId", "other"), ("cwd", "/tmp"),
                           ("itemId", None), ("command", params["command"] + ' && pwd')):
            self.assertFalse(approval_matches({**params, key: value}, report, work, marker))
        self.assertFalse(approval_matches(params, {"session_id": "owned-thread"}, work, marker))

    def test_native_inventory_must_be_complete_enabled_and_trusted(self):
        baseline = {"data": [{"errors": [], "warnings": [], "hooks": [
            {"enabled": True, "trustStatus": "trusted", "pluginId": "aidr-codex@aidr-local"}
            for _ in range(12)]}]}
        self.assertTrue(inventory_trusted(baseline))
        for field, value in (("enabled", False), ("trustStatus", "untrusted"),
                             ("trustStatus", "unknown"), ("pluginId", "another-plugin")):
            altered = copy.deepcopy(baseline)
            altered["data"][0]["hooks"][0][field] = value
            self.assertFalse(inventory_trusted(altered))
        altered = copy.deepcopy(baseline)
        altered["data"][0]["warnings"] = ["unreadable source"]
        self.assertFalse(inventory_trusted(altered))
        altered = copy.deepcopy(baseline)
        altered["data"][0]["hooks"].pop()
        self.assertFalse(inventory_trusted(altered))
        self.assertFalse(inventory_trusted({"data": []}))

    def test_owned_profile_requires_existing_acceptance_provenance(self):
        with tempfile.TemporaryDirectory(prefix="aidr-p3-codex-lifecycle-", dir="/private/tmp") as folder:
            root = Path(folder); home = root / "home"; home.mkdir()
            marker = root / "report.json"
            marker.write_text(json.dumps({"scope": "native_codex_lifecycle_audit"}))
            before = marker.read_bytes()
            self.assertEqual(owned_profile(home), home)
            self.assertEqual(marker.read_bytes(), before)
            marker.write_text(json.dumps({"scope": "unrelated"}))
            with self.assertRaisesRegex(ValueError, "native_profile_not_owned"):
                owned_profile(home)


if __name__ == "__main__":
    unittest.main()
