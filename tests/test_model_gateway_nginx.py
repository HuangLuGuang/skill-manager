"""Real proxy acceptance: RUN_GATEWAY_DOCKER_TESTS=1 uv run pytest this_file -q."""
import http.client
import json
import os
from pathlib import Path
import ssl
import subprocess
import time
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.environ.get('RUN_GATEWAY_DOCKER_TESTS') != '1', reason='Opt-in Docker integration')


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.STDOUT).strip()


def test_compose_model_listener_is_optional(tmp_path):
    env_file = tmp_path / '.env'
    env_file.write_text('MODEL_GATEWAY_HTTP_PORT=18000\nMODEL_GATEWAY_PUBLIC_URL=http://models.example.test:18000\n')
    base = ['compose', '--env-file', str(env_file), '-f', str(ROOT / 'docker-compose.yaml')]
    config = json.loads(docker(*base, 'config', '--format', 'json'))
    assert 'ports' not in config['services']['backend']
    assert not any(port['target'] == 8000 for port in config['services']['nginx']['ports'])
    for mode in ('http', 'https'):
        args = base + (['-f', str(ROOT / 'docker-compose.https.yaml'), '--profile', 'https'] if mode == 'https' else [])
        args += ['-f', str(ROOT / 'docker-compose.model-gateway.yaml')]
        config = json.loads(docker(*args, 'config', '--format', 'json'))
        assert 'ports' not in config['services']['backend']
        assert any(port['target'] == 8000 and port['published'] == '18000' for port in config['services']['nginx']['ports'])
        assert config['services']['backend']['environment']['MODEL_GATEWAY_PUBLIC_URL'] == 'http://models.example.test:18000'
    env_file.write_text('MODEL_GATEWAY_PUBLIC_URL=\n')
    result = subprocess.run(['docker', *args, 'config', '--quiet'], capture_output=True)
    assert result.returncode != 0, 'Enabled entry must require its client-accessible address'


@pytest.fixture(params=['http', 'https'])
def proxy(request, tmp_path):
    name = 'model-entry-' + uuid4().hex[:10]
    backend, nginx = name + '-backend', name + '-nginx'
    (tmp_path / 'upstream.py').write_text('''
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json, time
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({'path': self.path, 'authorization': self.headers.get('Authorization'),
                           'client_ip': self.headers.get('X-Forwarded-For')}).encode()
        if self.path.startswith('/api/') or self.headers.get('Authorization') == 'Bearer test-token':
            self.send_response(200)
        else:
            self.send_response(401)
        if self.path == '/v1/responses':
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            self.wfile.write(b'data: first\\n\\n'); self.wfile.flush()
            time.sleep(1)
            self.wfile.write(b'data: last\\n\\n'); self.wfile.flush()
        else:
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
    do_POST = do_GET
ThreadingHTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
''')
    docker('network', 'create', name)
    try:
        docker('run', '-d', '--name', backend, '--network', name, '--network-alias', 'backend',
               '--network-alias', 'frontend', '-v', f'{tmp_path}:/test:ro',
               'python:3.12-slim', 'python', '/test/upstream.py')
        args = ['run', '-d', '--name', nginx, '--network', name, '-p', '127.0.0.1::8000',
                '-p', '127.0.0.1::80', '-p', '127.0.0.1::443',
                '-v', f'{ROOT}/deploy/nginx/default.conf:/etc/nginx/http.conf:ro',
                '-v', f'{ROOT}/deploy/nginx/model-gateway.conf:/etc/nginx/conf.d/model-gateway.conf:ro']
        if request.param == 'https':
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                            '-subj', '/CN=localhost', '-keyout', str(tmp_path / 'key.pem'),
                            '-out', str(tmp_path / 'cert.pem')], check=True, capture_output=True)
            (tmp_path / 'server.pem').write_bytes((tmp_path / 'key.pem').read_bytes() + (tmp_path / 'cert.pem').read_bytes())
            args += ['-v', f'{tmp_path}:/certificates:ro', '-v', f'{ROOT}/deploy/nginx/https.sh:/etc/nginx/https.sh:ro',
                     '--entrypoint', '/bin/sh', 'nginx:1.27-alpine', '/etc/nginx/https.sh']
        else:
            args += ['--entrypoint', '/bin/sh', 'nginx:1.27-alpine', '-ec',
                     "cp /etc/nginx/http.conf /etc/nginx/conf.d/default.conf; exec nginx -g 'daemon off;'"]
        docker(*args)
        ports = json.loads(docker('inspect', nginx))[0]['NetworkSettings']['Ports']
        def connect(port):
            host_port = int(ports[f'{port}/tcp'][0]['HostPort'])
            if port == 443:
                return http.client.HTTPSConnection('127.0.0.1', host_port, timeout=5, context=ssl._create_unverified_context())
            return http.client.HTTPConnection('127.0.0.1', host_port, timeout=5)
        for _ in range(40):
            try:
                conn = connect(8000)
                conn.request('GET', '/v1/models')
                ready = conn.getresponse().status == 401
                conn.close()
                if ready:
                    break
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(.1)
        else:
            pytest.fail(docker('logs', nginx))
        yield connect, request.param
    finally:
        subprocess.run(['docker', 'rm', '-f', nginx, backend], capture_output=True)
        docker('network', 'rm', name)


def test_model_entry_routes_auth_streaming_and_management_isolation(proxy):
    connect, mode = proxy
    for method, path in [
        ('GET', '/models'), ('GET', '/v1/models'), ('GET', '/v1/models/provider/model'),
        ('POST', '/'), ('POST', '/v1/chat/completions'), ('POST', '/chat/completions'),
        ('POST', '/api/v1/llm/chat/completions'), ('POST', '/v1/messages'),
        ('POST', '/v1/messages/count_tokens'), ('POST', '/v1beta/models/demo:generateContent'),
        ('POST', '/v1beta/models/demo:streamGenerateContent?alt=sse'),
        ('POST', '/client-models/6162/v1/messages'),
        ('POST', '/client-models/6162/v1beta/models/demo:generateContent'),
    ]:
        conn = connect(8000)
        conn.request(method, path, headers={'Authorization': 'Bearer test-token', 'X-Forwarded-For': 'spoofed'})
        response = conn.getresponse()
        assert response.status == 200, (path, response.status)
        body = json.loads(response.read())
        assert body['path'] == path
        assert body['authorization'] == 'Bearer test-token'
        assert body['client_ip'] != 'spoofed'
        conn.close()
    for method, path in [('GET', '/api/v1/clients'), ('POST', '/api/auth/login'), ('GET', '/docs'),
                         ('POST', '/mcp/demo'), ('GET', '/uploads/a'), ('GET', '/v1/admin'),
                         ('GET', '/'), ('DELETE', '/v1/models'), ('GET', '/v1/messages')]:
        conn = connect(8000)
        conn.request(method, path)
        assert conn.getresponse().status in {403, 404}, path
        conn.close()
    conn = connect(8000)
    conn.request('GET', '/v1/models')
    assert conn.getresponse().status == 401
    conn.close()
    conn = connect(8000)
    started = time.monotonic()
    conn.request('POST', '/v1/responses', headers={'Authorization': 'Bearer test-token'})
    response = conn.getresponse()
    assert response.readline() == b'data: first\n'
    assert time.monotonic() - started < .8, 'First SSE chunk was buffered'
    assert b'data: last' in response.read()
    conn.close()
    conn = connect(80)
    conn.request('GET', '/api/probe')
    assert conn.getresponse().status == (308 if mode == 'https' else 200)
    conn.close()
    if mode == 'https':
        conn = connect(443)
        conn.request('GET', '/api/probe')
        assert conn.getresponse().status == 200
        conn.close()
