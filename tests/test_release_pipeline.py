from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CI = yaml.safe_load((ROOT / '.gitlab-ci.yml').read_text())


@pytest.mark.parametrize(('tag', 'branch', 'expected'), [
    ('', 'dev', {'deploy-35'}),
    ('', 'feature/test', set()),
    ('1.0.6', '', {'deploy-35', 'offline-package'}),
    ('v1.0.6', '', {'deploy-35', 'offline-package'}),
    ('1.0.6_arm', '', {'offline-package-arm'}),
    ('v1.0.6_arm', '', {'offline-package-arm'}),
    ('client-v26.10.09.1', '', set()),
    ('1.0.6_arm_extra', '', set()),
])
def test_tag_routes_to_requested_architecture(tag, branch, expected):
    selected = set()
    for name in ('deploy-35', 'offline-package', 'offline-package-arm'):
        for rule in CI[name]['rules']:
            expression = rule['if']
            if '=~' in expression:
                matches = re.search(expression.split('/', 1)[1].rsplit('/', 1)[0], tag)
            else:
                matches = branch == 'dev'
            if matches:
                selected.add(name)
    assert selected == expected
    for job in selected:
        assert set(CI[job].get('needs', [])) <= selected


@pytest.fixture
def release_run(tmp_path):
    messages = []
    downloads = []
    failure = {'at': ''}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            messages.append(payload[payload['msgtype']]['content'])
            if len(messages) == 2:
                assert payload['msgtype'] == 'markdown'
            code = 40014 if failure['at'] == 'notify' and len(messages) == 2 else 0
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({'errcode': code}).encode())

        def do_GET(self):
            downloads.append(self.path)
            archive = tmp_path / 'out' / self.path.rsplit('/', 1)[1]
            size = archive.stat().st_size
            if failure['at'] == 'download_size':
                size += 1
            status = 200 if failure['at'] == 'full_response' else 206
            self.send_response(403 if failure['at'] == 'download' else status)
            if status == 200:
                self.send_header('Content-Length', str(size))
            else:
                self.send_header('Content-Range', f'bytes 0-0/{size}')
            self.end_headers()
            if failure['at'] != 'download_empty':
                self.wfile.write(archive.read_bytes() if status == 200 else b'x')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f'http://127.0.0.1:{server.server_port}'
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    script_dir = tmp_path / 'scripts'
    script_dir.mkdir()
    shutil.copy(ROOT / 'scripts/verify-agent-manager-release-provenance.py', script_dir)
    shutil.copy(ROOT / 'scripts/publish_release_notification.py', script_dir)
    client = tmp_path / 'client'
    client.mkdir()
    (client / 'latest.json').write_text('{}')
    installer = tmp_path / 'installer.tar.gz'
    installer.write_bytes(b'installer')
    log = tmp_path / 'commands.jsonl'
    fake_tool = f'#!{sys.executable}\n' + r'''
import io, json, lzma, os, sys, tarfile
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['COMMAND_LOG'], 'a') as stream:
    stream.write(json.dumps([name, *args]) + '\n')
fail = os.environ['FAIL_AT']
if name == 'docker':
    if args[:2] == ['image', 'inspect']:
        print('sha256:original-x86-nginx' if '{{.Id}}' in args else 'amd64')
    elif args[:1] == ['run']:
        print('aarch64')
    elif args[:1] == ['load']:
        sys.stdin.buffer.read()
elif name == 'aws':
    if args[:2] == ['s3', 'cp'] and fail == 'upload':
        sys.exit(1)
    if args[:2] == ['s3', 'presign']:
        print(os.environ['DOWNLOAD_ENDPOINT'] + '/' + args[2].rsplit('/', 1)[1])
elif name == 'package-release.sh':
    if fail == 'build':
        sys.exit(1)
    version = args[args.index('-v') + 1]
    platform = args[args.index('-p') + 1]
    arch = {'linux/amd64': 'x86', 'linux/arm64': 'arm'}[platform]
    provenance = {
        'schema': 'agent-manager-release-provenance@1', 'version': version,
        'platform': platform, 'architecture': platform.split('/')[1],
        'archive_layout': arch, 'source_mode': 'git_clone', 'worktree_dirty': False,
        'git_commit': 'b' * 40 if fail == 'provenance' else os.environ['CI_COMMIT_SHA'],
        'generated_at': '2026-10-09T00:00:00Z',
    }
    output = Path(args[args.index('-o') + 1])
    output.mkdir(exist_ok=True)
    with tarfile.open(output / f'agent-manager_{version.removesuffix("_arm")}_{arch}.tar.gz', 'w:gz') as tar:
        for path, data in {
            'release-provenance.json': json.dumps(provenance).encode(),
            f'docker_images/{arch}/agent-manager-images-{version}.tar.xz': lzma.compress(b'fake-image'),
        }.items():
            entry = tarfile.TarInfo('agent-manager/' + path)
            entry.size = len(data)
            tar.addfile(entry, io.BytesIO(data))
elif name.startswith('verify-') and fail == 'image':
    sys.exit(1)
'''
    for path in (bin_dir / 'docker', bin_dir / 'aws', tmp_path / 'package-release.sh',
                 script_dir / 'verify-agent-security-worker-image.sh',
                 script_dir / 'verify-aig-scan-service-image.sh'):
        path.write_text(fake_tool)
        path.chmod(0o755)

    def run(arch, fail=''):
        failure['at'] = fail
        job = 'offline-package-arm' if arch == 'arm' else 'offline-package'
        env = dict(os.environ, **CI['.release-on-35']['variables'], **CI[job]['variables'])
        env.update(
            PATH=str(bin_dir) + os.pathsep + os.environ['PATH'],
            COMMAND_LOG=str(log), FAIL_AT=fail, DOWNLOAD_ENDPOINT=endpoint + '/download',
            WECHAT_WEBHOOK_URL=endpoint + '/notify', CI_PIPELINE_URL='https://ci.example/pipeline/1',
            CI_COMMIT_TAG='1.0.6_arm' if arch == 'arm' else '1.0.6', CI_COMMIT_SHA='a' * 40,
            DOCKER_INSTALLER=str(installer), CLIENT_RELEASES=str(client), RELEASE_DIR=str(tmp_path / 'out'),
        )
        result = subprocess.run(['bash', '-c', CI['.offline-package']['script'][0]],
                                cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
        commands = [json.loads(line) for line in log.read_text().splitlines()]
        return result, commands, messages, downloads

    yield run
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize('arch', ['x86', 'arm'])
def test_release_publishes_one_archive_and_download_link(release_run, arch):
    result, commands, messages, downloads = release_run(arch)
    assert result.returncode == 0, result.stdout + result.stderr
    packages = [cmd for cmd in commands if cmd[0] == 'package-release.sh']
    assert len(packages) == 1
    assert packages[0][packages[0].index('-p') + 1] == ('linux/arm64' if arch == 'arm' else 'linux/amd64')
    version = '1.0.6_arm' if arch == 'arm' else '1.0.6'
    image_arch = 'arm64' if arch == 'arm' else 'amd64'
    for component in ('agent-security-worker', 'aig-scan-service'):
        assert [f'verify-{component}-image.sh', f'agent-manager-{component.removeprefix("agent-")}:{version}', image_arch] in commands
    uploads = [cmd for cmd in commands if cmd[:3] == ['aws', 's3', 'cp']]
    assert len(uploads) == 1
    assert uploads[0][3].endswith(f'agent-manager_1.0.6_{arch}.tar.gz')
    assert downloads == [f'/download/agent-manager_1.0.6_{arch}.tar.gz']
    assert len(messages) == 2
    assert 'http://127.0.0.1:' in messages[-1]
    assert downloads[0] in messages[-1]
    assert '7 天' in messages[-1]
    assert '604800 秒' not in messages[-1]
    assert '[点击下载]' not in messages[-1]
    assert any(line.startswith('http://127.0.0.1:') and line.endswith(downloads[0])
               for line in messages[-1].splitlines())
    archive = Path(uploads[0][3])
    assert hashlib.md5(archive.read_bytes()).hexdigest() in messages[-1]
    assert '>大小：' in messages[-1]
    assert f'>文件：{archive.name}' in messages[-1]
    restores = [cmd for cmd in commands if cmd[:3] == ['docker', 'image', 'tag']]
    if arch == 'arm':
        assert restores == [['docker', 'image', 'tag', 'sha256:original-x86-nginx', 'nginx:1.27-alpine']]
        assert commands.index(restores[0]) < commands.index(uploads[0])
    else:
        assert not restores
        assert not any('linux/arm64' in cmd for cmd in commands)


@pytest.mark.parametrize('fail', [
    'build', 'provenance', 'image', 'upload', 'download', 'download_size', 'download_empty', 'notify',
])
def test_release_failure_does_not_report_success_and_restores_nginx(release_run, fail):
    result, commands, messages, downloads = release_run('arm', fail)
    assert result.returncode != 0
    assert ['docker', 'image', 'tag', 'sha256:original-x86-nginx', 'nginx:1.27-alpine'] in commands
    if fail in {'build', 'provenance', 'image'}:
        assert not any(cmd[:3] == ['aws', 's3', 'cp'] for cmd in commands)
    if fail != 'notify':
        assert len(messages) == 1
    if fail == 'notify':
        assert '企业微信通知失败，errcode=40014' in result.stderr
    if fail == 'download_size':
        assert 'S3 文件大小与本地产物不一致' in result.stderr


def test_release_accepts_full_download_response_with_matching_size(release_run):
    result, _, messages, _ = release_run('x86', 'full_response')
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(messages) == 2
