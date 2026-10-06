#!/usr/bin/env python3
"""Root-only, read-only relay for es-continuous-observer JSON records."""
import argparse
import asyncio
import ctypes
import errno
import json
import os
import pwd
import signal
import socket
import stat
import time
from pathlib import Path

PROTOCOL = 1
MAX_FRAME = 64 * 1024
CLIENT_QUEUE = 128
LIBC = ctypes.CDLL(None, use_errno=True)


def fail(code):
    raise RuntimeError(code)


def secure_chain(path, include_leaf=False):
    path = Path(os.path.abspath(path))
    parts = path.parts if include_leaf else path.parent.parts
    current = Path(parts[0])
    for part in parts[1:]:
        current /= part
        info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode):
            fail("runtime_relay_unsafe_path")
        if info.st_uid != 0 or info.st_mode & 0o022:
            fail("runtime_relay_unsafe_path")


def secure_executable(path):
    secure_chain(path, True)
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or not info.st_mode & stat.S_IXUSR:
        fail("runtime_relay_invalid_observer")


def open_secure_log(path):
    secure_chain(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        os.close(fd); fail("runtime_relay_unsafe_log")
    return os.fdopen(fd, "ab", buffering=0)


def peer_uid(writer):
    transport_socket = writer.get_extra_info("socket")
    uid = ctypes.c_uint()
    gid = ctypes.c_uint()
    result = LIBC.getpeereid(transport_socket.fileno(), ctypes.byref(uid), ctypes.byref(gid))
    if result != 0:
        return None
    return uid.value


class Relay:
    def __init__(self, allowed_uid, health_timeout):
        self.allowed_uid = allowed_uid
        self.health_timeout = health_timeout
        self.clients = set()
        self.session = ""
        self.session_ready = asyncio.Event()
        self.coverage = "unknown"
        self.last_health = 0.0
        self.sequence = 0
        self.process = None
        self.stopping = False
        self.active_connections = 0

    def frame(self, kind, **values):
        self.sequence += 1
        return {"protocol": PROTOCOL, "type": kind, "sequence": self.sequence,
                "monitor_session": self.session, **values}

    async def accept(self, reader, writer):
        del reader
        if self.active_connections >= 16:
            writer.close(); await writer.wait_closed(); return
        self.active_connections += 1
        if peer_uid(writer) != self.allowed_uid:
            self.active_connections -= 1
            writer.close(); await writer.wait_closed(); return
        try:
            await asyncio.wait_for(self.session_ready.wait(), self.health_timeout)
        except asyncio.TimeoutError:
            self.active_connections -= 1
            writer.close(); await writer.wait_closed(); return
        queue = asyncio.Queue(CLIENT_QUEUE)
        task = asyncio.create_task(self.write_client(writer, queue))
        item = (queue, task, writer)
        self.clients.add(item)
        try:
            await queue.put(self.frame("hello", stream_start="late_join",
                                      attribution_baseline="unknown",
                                      transport="connected",
                                      observer_health=self.health_state()))
            await queue.put(self.frame("status", transport="connected",
                                      observer_health=self.health_state(),
                                      coverage=self.coverage,
                                      reason="late_join_no_history"))
            await task
        finally:
            self.active_connections -= 1
            self.clients.discard(item)
            task.cancel(); writer.close(); await writer.wait_closed()

    async def write_client(self, writer, queue):
        try:
            while True:
                frame = await queue.get()
                writer.write(json.dumps(frame, separators=(",", ":")).encode() + b"\n")
                await asyncio.wait_for(writer.drain(), 1.0)
        except (ConnectionError, asyncio.TimeoutError, asyncio.CancelledError):
            return

    def health_state(self):
        if not self.last_health: return "starting"
        return "healthy" if time.monotonic() - self.last_health <= self.health_timeout else "stale"

    async def broadcast(self, frame):
        if len(json.dumps(frame, separators=(",", ":")).encode()) > MAX_FRAME:
            await self.status("degraded", "observer_frame_too_large"); return
        for item in list(self.clients):
            queue, task, writer = item
            if queue.full():
                self.clients.discard(item); task.cancel(); writer.close(); continue
            queue.put_nowait(frame)

    async def status(self, health, reason):
        await self.broadcast(self.frame("status", transport="connected",
                                        observer_health=health,
                                        coverage=self.coverage, reason=reason))

    async def read_observer(self):
        while True:
            line = await self.process.stdout.readline()
            if not line: break
            if len(line) > MAX_FRAME:
                await self.status("degraded", "observer_frame_too_large"); continue
            try: payload = json.loads(line)
            except json.JSONDecodeError:
                await self.status("degraded", "observer_invalid_json"); continue
            incoming = payload.get("monitor_session", "")
            if incoming and incoming != self.session:
                if self.session:
                    await self.status("degraded", "unexpected_monitor_session_change")
                    return 74
                self.session = incoming; self.coverage = "unknown"; self.session_ready.set()
            reported_coverage = payload.get("coverage")
            if reported_coverage in ("complete", "degraded"):
                self.coverage = reported_coverage
            if payload.get("event") == "observer_health":
                self.last_health = time.monotonic()
                self.coverage = payload.get("coverage", "unknown")
                await self.status("healthy", "observer_heartbeat")
            await self.broadcast(self.frame("event", transport="connected",
                                            observer_health=self.health_state(),
                                            coverage=self.coverage, payload=payload))
        code = await self.process.wait()
        await self.status("offline", f"observer_exit_{code}")
        return code

    async def health_loop(self):
        previous = ""
        while not self.stopping:
            current = self.health_state()
            if current != previous:
                await self.status(current, "observer_health_state_changed")
                previous = current
            await asyncio.sleep(min(1.0, self.health_timeout / 2))


async def async_main(args):
    socket_path = Path(os.path.abspath(args.socket))
    observer = Path(os.path.abspath(args.observer))
    ready = socket_path.with_suffix(".observer-ready")
    secure_chain(socket_path)
    secure_executable(observer)
    if socket_path.exists() or socket_path.is_symlink(): fail("runtime_relay_socket_exists")
    if ready.exists() or ready.is_symlink(): fail("runtime_relay_ready_exists")
    log = open_secure_log(args.observer_stderr)
    relay = Relay(args.allow_uid, args.health_timeout)
    command = [str(observer), "--ready", str(ready), "--duration", str(args.duration),
               "--health-interval", str(args.heartbeat), *args.catalog]
    server = None
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM): loop.add_signal_handler(sig, stop.set)
    try:
        relay.process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=log,
            start_new_session=True)
        server = await asyncio.start_unix_server(relay.accept, path=str(socket_path))
        os.chown(socket_path, args.allow_uid, pwd.getpwuid(args.allow_uid).pw_gid)
        os.chmod(socket_path, 0o600)
        health_task = asyncio.create_task(relay.health_loop())
        reader_task = asyncio.create_task(relay.read_observer())
        stop_task = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait((reader_task, stop_task), return_when=asyncio.FIRST_COMPLETED)
        code = reader_task.result() if reader_task in done else 0
        health_task.cancel(); reader_task.cancel(); stop_task.cancel()
        return code
    finally:
        relay.stopping = True
        if server is not None: server.close(); await server.wait_closed()
        for _, task, writer in list(relay.clients): task.cancel(); writer.close()
        if relay.process is not None:
            process_group = relay.process.pid
            try: os.killpg(process_group, signal.SIGCONT)
            except ProcessLookupError: pass
            if relay.process.returncode is None:
                relay.process.send_signal(signal.SIGTERM)
                try: await asyncio.wait_for(relay.process.wait(), 3)
                except asyncio.TimeoutError: pass
            try: os.killpg(process_group, signal.SIGKILL)
            except ProcessLookupError: pass
            if relay.process.returncode is None:
                await asyncio.wait_for(relay.process.wait(), 1)
        socket_path.unlink(missing_ok=True); ready.unlink(missing_ok=True); log.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True); parser.add_argument("--allow-uid", required=True, type=int)
    parser.add_argument("--observer", required=True); parser.add_argument("--duration", type=int, default=86400)
    parser.add_argument("--heartbeat", type=int, default=2); parser.add_argument("--health-timeout", type=float, default=6.0)
    parser.add_argument("--observer-stderr", required=True); parser.add_argument("--catalog", action="append", required=True)
    args = parser.parse_args()
    if os.geteuid() != 0: fail("runtime_relay_requires_root")
    secure_chain(__file__, True)
    if not 1 <= args.heartbeat <= 60 or args.health_timeout <= args.heartbeat: fail("runtime_relay_invalid_health_interval")
    try: code = asyncio.run(async_main(args))
    except RuntimeError as error: print(error, file=os.sys.stderr); code = 78
    raise SystemExit(code)


if __name__ == "__main__": main()
