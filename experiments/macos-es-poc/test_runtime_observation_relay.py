import importlib.util
import os
import stat
import tempfile
import unittest
from unittest import mock
import asyncio
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("relay", Path(__file__).with_name("runtime_observation_relay.py"))
relay = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(relay)


class RelayTests(unittest.IsolatedAsyncioTestCase):
    def test_health_does_not_depend_on_business_events(self):
        value = relay.Relay(os.getuid(), .05)
        self.assertEqual("starting", value.health_state())
        value.last_health = relay.time.monotonic()
        self.assertEqual("healthy", value.health_state())
        value.last_health -= .1
        self.assertEqual("stale", value.health_state())

    def test_world_writable_ancestor_rejected(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as root:
            os.chmod(root, 0o777)
            with self.assertRaisesRegex(RuntimeError, "unsafe_path"):
                relay.secure_chain(Path(root) / "runtime.sock")

    async def test_full_client_queue_is_disconnected(self):
        value = relay.Relay(os.getuid(), 1)
        slow_queue = asyncio.Queue(1); slow_queue.put_nowait({"occupied": True})
        healthy_queue = asyncio.Queue(1)
        slow_task = asyncio.create_task(asyncio.sleep(10))
        healthy_task = asyncio.create_task(asyncio.sleep(10))
        slow_writer = mock.Mock(); healthy_writer = mock.Mock()
        value.clients = {(slow_queue, slow_task, slow_writer),
                         (healthy_queue, healthy_task, healthy_writer)}
        await value.broadcast(value.frame("status", observer_health="healthy"))
        self.assertNotIn((slow_queue, slow_task, slow_writer), value.clients)
        await asyncio.sleep(0)
        self.assertTrue(slow_task.cancelled())
        slow_writer.close.assert_called_once()
        self.assertEqual("status", (await healthy_queue.get())["type"])
        healthy_task.cancel()

    async def test_hung_drain_returns_within_writer_timeout(self):
        class Writer:
            def write(self, data): self.data = data
            async def drain(self): await asyncio.sleep(10)
        value = relay.Relay(os.getuid(), 1)
        queue = asyncio.Queue(); await queue.put({"protocol": 1})
        await asyncio.wait_for(value.write_client(Writer(), queue), 1.2)


if __name__ == "__main__": unittest.main()
