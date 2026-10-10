import tempfile
import unittest
from pathlib import Path

from snapshot_attribution import Component, ProcessIdentity, ProcessRecord, classify_snapshot


class SnapshotAttributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.real = base / "real-agent"
        self.real.touch()
        self.component = Component("codex", "cli", "backend", str(self.real), True)

    def tearDown(self):
        self.temp.cleanup()

    def record(self, pid, start, ppid, path):
        return ProcessRecord(ProcessIdentity(pid, start), ppid, str(path))

    def test_same_name_spoof_and_path_change_do_not_match(self):
        fake = Path(self.temp.name) / "other" / self.real.name
        fake.parent.mkdir(); fake.touch()
        self.assertEqual([], classify_snapshot([self.record(10, 1, 1, fake)], [self.component]))
        moved = Path(self.temp.name) / "moved-agent"; moved.touch()
        self.assertEqual([], classify_snapshot([self.record(10, 1, 1, moved)], [self.component]))

    def test_pid_reuse_is_a_distinct_identity(self):
        old = self.record(10, 100, 1, self.real)
        child = self.record(11, 110, 10, "/bin/sh")
        reused = self.record(10, 200, 1, "/bin/sh")
        self.assertEqual("inferred", classify_snapshot([old, child], [self.component])[1]["attribution"])
        self.assertEqual([], classify_snapshot([reused, child], [self.component]))

    def test_reused_pid_at_same_agent_path_cannot_adopt_older_child(self):
        reused_root = self.record(10, 300, 1, self.real)
        older_child = self.record(11, 200, 10, "/bin/sh")
        results = classify_snapshot([reused_root, older_child], [self.component])
        self.assertEqual(["snapshot"], [item["attribution"] for item in results])

    def test_conflicting_same_pid_records_are_unknown(self):
        first = self.record(10, 100, 1, self.real)
        reused = self.record(10, 200, 1, self.real)
        child = self.record(11, 210, 10, "/bin/sh")
        diagnostics = {}
        self.assertEqual([], classify_snapshot([first, reused, child], [self.component], diagnostics))
        self.assertEqual(1, diagnostics["conflicted_pids"])

    def test_parent_newer_than_child_cannot_be_ancestry(self):
        root = self.record(10, 200, 1, self.real)
        child = self.record(11, 100, 10, "/bin/sh")
        results = classify_snapshot([root, child], [self.component])
        self.assertEqual(["snapshot"], [item["attribution"] for item in results])

    def test_multiple_roots_remain_separate(self):
        second_path = Path(self.temp.name) / "claude"; second_path.touch()
        second = Component("claude", "cli", "cli_native", str(second_path), True)
        records = [self.record(10, 1, 1, self.real), self.record(20, 2, 1, second_path),
                   self.record(11, 3, 10, "/bin/sh"), self.record(21, 4, 20, "/bin/sh")]
        results = classify_snapshot(records, [self.component, second])
        roots = {(item["pid"], item["root"]["pid"]) for item in results if item["attribution"] == "inferred"}
        self.assertEqual({(11, 10), (21, 20)}, roots)

    def test_parent_exit_and_snapshot_gap_stay_unknown(self):
        orphan = self.record(11, 3, 10, "/bin/sh")
        self.assertEqual([], classify_snapshot([orphan], [self.component]))

    def test_inferred_child_is_not_a_native_component_or_root(self):
        records = [self.record(10, 100, 1, self.real), self.record(11, 110, 10, "/bin/sh")]
        child = next(item for item in classify_snapshot(records, [self.component]) if item["pid"] == 11)
        self.assertFalse(child["root_candidate"])
        self.assertEqual("unclassified_descendant", child["component_role"])
        self.assertEqual("backend", child["root_component_role"])
        self.assertEqual("snapshot_ppid_chain", child["identity_basis"])

    def test_helper_is_snapshot_but_not_an_ancestry_root(self):
        helper_path = Path(self.temp.name) / "helper"; helper_path.touch()
        helper = Component("claude", "desktop", "helper", str(helper_path), False)
        records = [self.record(10, 1, 1, helper_path), self.record(11, 2, 10, "/bin/sh")]
        results = classify_snapshot(records, [helper])
        self.assertEqual(1, len(results)); self.assertEqual("snapshot", results[0]["attribution"])

    def test_permission_denial_is_represented_by_omission_not_pid_guess(self):
        readable = self.record(10, 1, 1, self.real)
        self.assertEqual([], classify_snapshot([], [self.component]))
        self.assertEqual("snapshot", classify_snapshot([readable], [self.component])[0]["attribution"])


if __name__ == "__main__":
    unittest.main()
