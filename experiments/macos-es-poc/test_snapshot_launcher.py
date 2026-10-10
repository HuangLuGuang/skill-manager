import errno
import os
import select
import subprocess
import unittest
from pathlib import Path


LAUNCHER = Path(__file__).resolve().parent / "build/snapshot-launcher"


class SnapshotLauncherTests(unittest.TestCase):
    def start(self, *command, timeout="500"):
        process = subprocess.Popen([str(LAUNCHER), "--timeout-ms", timeout, *command],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        ready, _, _ = select.select([process.stdout], [], [], 2)
        self.assertTrue(ready)
        return process, int(process.stdout.readline().strip())

    def assert_gone(self, pid):
        try:
            os.kill(pid, 0)
        except OSError as error:
            self.assertEqual(errno.ESRCH, error.errno)
        else:
            self.fail(f"owned child {pid} remains")

    def test_spawn_failure(self):
        result = subprocess.run([str(LAUNCHER), "--timeout-ms", "100", "/no/such/executable"],
                                capture_output=True, timeout=2)
        self.assertEqual(71, result.returncode)

    def test_handshake_timeout_reaps_owned_child(self):
        process, pid = self.start("/bin/sleep", "30", timeout="100")
        process.communicate(timeout=2)
        self.assertEqual(72, process.returncode); self.assert_gone(pid)

    def test_parent_termination_reaps_owned_child(self):
        process, pid = self.start("/bin/sleep", "30", timeout="5000")
        process.terminate(); process.communicate(timeout=2)
        self.assertEqual(72, process.returncode); self.assert_gone(pid)

    def test_runtime_timeout_reaps_owned_child(self):
        process, pid = self.start("/bin/sleep", "30", timeout="100")
        process.communicate("c", timeout=2)
        self.assertEqual(124, process.returncode); self.assert_gone(pid)


if __name__ == "__main__":
    unittest.main()
