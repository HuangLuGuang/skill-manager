import time
import unittest

from observe_agents import ProcessReader, attach_classification_coverage
from snapshot_attribution import ProcessIdentity


class FakeReader(ProcessReader):
    def __init__(self, listing, infos=None, paths=None, path_delay=0):
        self.listing = listing
        self.infos = infos or {}
        self.paths = paths or {}
        self.path_delay = path_delay

    def _list_pids(self, maximum):
        return self.listing

    def info(self, pid):
        return self.infos.get(pid)

    def path(self, pid):
        if self.path_delay:
            time.sleep(self.path_delay)
        return self.paths.get(pid)


class ProcessReaderCoverageTests(unittest.TestCase):
    def test_second_process_list_failure_is_unavailable(self):
        records, coverage = FakeReader((-1, 64, [])).snapshot(64)
        self.assertEqual([], records)
        self.assertEqual("unavailable", coverage["status"])

    def test_permission_style_identity_omission_is_partial(self):
        records, coverage = FakeReader((1, 64, [10])).snapshot(64)
        self.assertEqual([], records)
        self.assertEqual("partial", coverage["status"])
        self.assertEqual(1, coverage["errors"]["identity_unavailable"])

    def test_duration_budget_is_partial(self):
        identity = (ProcessIdentity(10, 100), 1)
        reader = FakeReader((1, 64, [10]), {10: identity}, {10: "/bin/sh"}, path_delay=0.02)
        records, coverage = reader.snapshot(64, max_duration_ms=10)
        self.assertEqual([], records)
        self.assertEqual("partial", coverage["status"])
        self.assertEqual(1, coverage["errors"]["duration_limit"])

    def test_classification_conflict_or_budget_marks_partial(self):
        for classification in ({"conflicted_pids": 1, "truncated": False},
                               {"conflicted_pids": 0, "truncated": True}):
            coverage = {"status": "complete"}
            attach_classification_coverage(coverage, classification)
            self.assertEqual("partial", coverage["status"])


if __name__ == "__main__":
    unittest.main()
