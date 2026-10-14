#!/usr/bin/env python3
"""Exercise real proxy exec handoff with two built CLI binaries (macOS only).
Usage: python3 scripts/test-teleagent-upgrade.py OLD_BINARY NEW_BINARY
Uses isolated state and a loopback streaming fixture; never touches host config.
"""
import concurrent.futures
import hashlib
import http.client
import http.server
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time

old, new = map(lambda s: str(Path(s).resolve()), sys.argv[1:3])
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(old) != sha(new), 'Use two distinct builds'
started, release = threading.Event(), threading.Event()
class Upstream(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        if self.path == '/stream':
            self.wfile.write(b'data: first\n\n'); self.wfile.flush(); started.set()
            assert release.wait(20)
            self.wfile.write(b'data: last\n\n'); self.wfile.flush()
        else:
            self.wfile.write(b'ready')
upstream = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
threading.Thread(target=upstream.serve_forever, daemon=True).start()
with tempfile.TemporaryDirectory(prefix='am-proxy-upgrade-') as home:
    root = Path(home)/'.agent-manager/aidr'; root.mkdir(parents=True, mode=0o700)
    service = root/'teleagent-proxy'; service.mkdir(mode=0o700)
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    secret = secrets.token_hex(32)
    (root/'teleagent-desktop.json').write_text(json.dumps(dict(address=f'127.0.0.1:{port}', secret=secret, upstream=f'http://127.0.0.1:{upstream.server_port}', installed=False)))
    def request(path):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        try:
            conn.request('GET', path, headers={'Host': f'{secret[:32]}.{secret[32:]}.localhost:{port}'})
            r = conn.getresponse(); b = r.read(); assert r.status == 200, r.status; return b
        finally: conn.close()
    def status(): return json.loads(request('/_agent_manager/status'))
    def wait_for(predicate, seconds=12):
        until = time.monotonic()+seconds
        while time.monotonic()<until:
            try:
                value=status()
                if predicate(value): return value
            except (OSError, http.client.HTTPException): pass
            time.sleep(.025)
        raise AssertionError('proxy did not reach expected state')
    def stage(binary):
        tmp=service/'desired.tmp'; tmp.write_text(json.dumps(dict(binary=binary, sha256=sha(binary)))); tmp.replace(service/'desired.json')
    proc = subprocess.Popen([old,'aidr-teleagent-service','--home',home], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        first=wait_for(lambda s:s['health']=='healthy')
        # Invalid candidate must leave the old listener and version intact.
        bad=service/'invalid'; bad.write_text('invalid executable'); bad.chmod(0o700);stage(str(bad))
        rejected=wait_for(lambda s:s['upgrade']=='failed')
        assert rejected['runtime']['sha256']==sha(old)
        assert request('/model')==b'ready'
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            stream=pool.submit(request,'/stream'); assert started.wait(5)
            stage(new)
            pending=wait_for(lambda s:s['upgrade']=='waiting_idle')
            time.sleep(2)
            assert status()['runtime']['sha256']==sha(old)
            stop=threading.Event(); observations=[]
            def traffic():
                while not stop.is_set():
                    before=time.monotonic()
                    assert request('/model')==b'ready'
                    observations.append(time.monotonic()-before)
                    time.sleep(.01)
            traffic_run=pool.submit(traffic)
            release.set()
            assert stream.result()==b'data: first\n\ndata: last\n\n'
            final=wait_for(lambda s:s['runtime']['sha256']==sha(new))
            stop.set();traffic_run.result()
        assert final['runtime']['pid']==first['runtime']['pid']==proc.pid
        print(json.dumps(dict(pid_preserved=True, stream_complete=True, rejected_candidate_preserved=True, concurrent_requests=len(observations), max_latency_ms=round(max(observations)*1000,2), old_sha=sha(old), new_sha=sha(new))))
    finally:
        release.set();proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill();proc.wait()
        upstream.shutdown()
