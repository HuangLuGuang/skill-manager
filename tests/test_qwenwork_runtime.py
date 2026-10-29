"""Opt-in local desktop acceptance host; only a disposable project is collected."""
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time

import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization

from tests.test_aidr_api import service
from tests.test_aidr_enforcement import control
from tests.test_aidr_content import configure
from backend import models


@pytest.mark.skipif(not os.environ.get('QWENWORK_ACCEPTANCE_ROOT'), reason='requires owned desktop acceptance project')
def test_desktop_acceptance_host(control):
    client, factory, key = control
    root = Path(os.environ['QWENWORK_ACCEPTANCE_ROOT']).resolve()
    assert root.is_dir() and (root / 'project').is_dir()
    assert root.stat().st_mode & 0o077 == 0, 'receiver directory must be private'
    configure(factory)
    binary = root / 'agent-manager-client'
    subprocess.run(['go', 'build', '-o', str(binary), './cmd/agent-manager-client'],
                   cwd=Path(__file__).resolve().parents[1] / 'scanner', check=True, timeout=120)
    public = root / 'public.x963'
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(client.app, log_level='critical', access_log=False, lifespan='off'))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{listener.getsockname()[1]}'
    processes = []
    logs = []
    try:
        common = ['--server', url, '--client-id', 'one', '--token-env', 'AIDR_TEST_TOKEN']
        commands = [
            ['aidr-hook-serve', '--state-dir', str(root/'state'), '--socket', str(root/'h.sock'), '--public-key', str(public)],
            ['aidr-sync', '--state-dir', str(root/'log-state'), '--source', 'qwenwork='+str(Path.home()/'.qwenworkcn/projects/-private-tmp-aidr-qwenwork-research-project')],
        ]
        for index, command in enumerate(commands):
            log = (root/f'service-{index}.log').open('w')
            logs.append(log)
            processes.append(subprocess.Popen([str(binary), *command, *common], env={**os.environ, 'AIDR_TEST_TOKEN':'test-one'}, stdout=log, stderr=log))
        (root/'ready.json').write_text(json.dumps({'url':url, 'socket':str(root/'h.sock')}))
        deadline = time.monotonic()+3600
        while not (root/'finish').exists() and time.monotonic()<deadline:
            assert all(p.poll() is None for p in processes)
            time.sleep(.5)
        assert (root/'finish').exists(), 'acceptance deadline exceeded'
        if os.environ.get('QWENWORK_ACCEPTANCE_REPLAY'):
            expected = int(os.environ['QWENWORK_EXPECTED_EVENTS'])
            def count():
                with factory() as db:
                    return db.query(models.AidrEvent).count()
            deadline = time.monotonic()+30
            while count() < expected and time.monotonic() < deadline:
                time.sleep(.2)
            assert count() == expected
            processes[1].terminate()
            processes[1].wait(timeout=10)
            command = [str(binary), *commands[1], *common, '--duration', '5s']
            restarted = subprocess.run(command, env={**os.environ, 'AIDR_TEST_TOKEN':'test-one'}, capture_output=True, timeout=20)
            assert restarted.returncode == 0, restarted.stderr.decode()
            assert count() == expected
            # Fresh cursor re-reads the same native files on a new stream; logical IDs still deduplicate.
            command[command.index(str(root/'log-state'))] = str(root/'replay-state')
            replayed = subprocess.run(command, env={**os.environ, 'AIDR_TEST_TOKEN':'test-one'}, capture_output=True, timeout=20)
            assert replayed.returncode == 0, replayed.stderr.decode()
            assert count() == expected
            (root/'restart-result.json').write_text(json.dumps({'events_before':expected,'events_after_restart':count(),'events_after_fresh_cursor':count()}))
        events = client.get('/api/v1/clients/one/aidr/events?limit=100').json()
        approvals = client.get('/api/v1/clients/one/aidr/hook-approvals').json()
        (root/'platform-events.json').write_text(json.dumps(events, ensure_ascii=False, indent=2))
        (root/'platform-approvals.json').write_text(json.dumps(approvals, ensure_ascii=False, indent=2))
        assert events['items']
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for log in logs:
            log.close()
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
