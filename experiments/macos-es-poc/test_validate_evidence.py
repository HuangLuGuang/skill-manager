#!/usr/bin/env python3
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from validate_evidence import validate


class EvidenceValidationTest(unittest.TestCase):
    def fixture(self, mutate=None):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        pid, parent, version = 123, 77, 9
        records = [
            {"event": "fork", "pid": pid, "pidversion": 8, "parent_pid": parent},
            {"event": "exec", "pid": pid, "pidversion": version, "parent_pid": parent},
            *[{"event": "auth_open", "pid": pid, "pidversion": version, "decision": "deny",
               "response": 0, "cache": False, "deadline_remaining_ticks": 1} for _ in range(100)],
            {"event": "exit", "pid": pid, "pidversion": version, "parent_pid": parent},
            {"event": "exec", "pid": 1234, "pidversion": 10, "parent_pid": parent},
        ]
        result = {"pid": pid, "protected_denied": 100, "protected_unexpected_success": 0,
                  "allowed_success": 100, "allowed_failures": 0}
        if mutate:
            mutate(records, result)
        log = directory / "events.jsonl"
        log.write_text("".join(json.dumps(record) + "\n" for record in records))
        result_path = directory / "result.json"
        result_path.write_text(json.dumps(result))
        stderr = directory / "stderr"
        stderr.write_text("SUMMARY response_errors=0 dropped_logs=0 log_drain=complete\n")
        return log, result_path, stderr, parent

    def test_accepts_correlated_evidence_and_ignores_pid_prefix(self):
        validate(*self.fixture())

    def test_rejects_auth_from_wrong_instance(self):
        fixture = self.fixture(lambda records, _: records[2].update(pidversion=99))
        with self.assertRaisesRegex(ValueError, "pidversion"):
            validate(*fixture)

    def test_rejects_unsuccessful_denial(self):
        fixture = self.fixture(lambda records, _: records[2].update(response=1))
        with self.assertRaisesRegex(ValueError, "non-success"):
            validate(*fixture)

    def test_rejects_pid_prefix_substitution(self):
        def mutate(records, _):
            for record in records:
                if record.get("pid") == 123:
                    record["pid"] = 1234
        with self.assertRaisesRegex(ValueError, "missing correlated"):
            validate(*self.fixture(mutate))

    def test_rejects_zero_deadline_margin(self):
        fixture = self.fixture(lambda records, _: records[2].update(deadline_remaining_ticks=0))
        with self.assertRaisesRegex(ValueError, "deadline"):
            validate(*fixture)


if __name__ == "__main__":
    unittest.main()
