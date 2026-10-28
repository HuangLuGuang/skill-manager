from __future__ import annotations

import fcntl
import io
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Deployment targets Linux system tools')


def make_release(root, version='1.0.7', platform='linux/amd64'):
    root.mkdir(parents=True, exist_ok=True)
    for name in ('start.sh', 'upgrade.sh', 'deploy/offline.sh', '.env.example',
                 'docker-compose.https.yaml', 'deploy/nginx/https.sh', 'deploy/nginx/certificates.py',
                 'deploy/nginx/default.conf', 'docs/offline-deployment.md', 'docs/docker-deployment.md', 'docs/license.md'):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    (root / 'docker-compose.yaml').write_text(
        (ROOT / 'docker-compose.yaml').read_text().replace('${TAG:-latest}', version))
    (root / 'release-provenance.json').write_text(json.dumps({'version': version, 'platform': platform}))
    (root / 'release-info').write_text(f'{version}\n{platform}\n')
    arch = 'arm' if platform == 'linux/arm64' else 'x86'
    image = root / f'docker_images/{arch}/agent-manager-images-{version}.tar.xz'
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(lzma.compress(b'offline-images'))
    (root / 'scanner/releases').mkdir(parents=True, exist_ok=True)
    (root / 'scanner/releases/latest.json').write_text(json.dumps({'version': version}))
    return root


def package(source, target):
    with tarfile.open(target, 'w:gz') as archive:
        archive.add(source, arcname='agent-manager')
    return target


@pytest.fixture
def installation(tmp_path):
    root = make_release(tmp_path / 'existing install', '1.0.6')
    (root / '.env').write_text('TAG=old-version\nSECRET_KEY=customer-secret\nINITIAL_ADMIN_PASSWORD=unchanged\n')
    (root / '.env').chmod(0o600)
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    for name in ('bash', 'dirname', 'cat', 'timeout', 'flock', 'tar', 'awk', 'mktemp',
                 'cp', 'chmod', 'mv', 'mkdir', 'rm', 'date', 'find', 'gzip'):
        (binaries / name).symlink_to(shutil.which(name))
    log = tmp_path / 'docker.jsonl'
    docker = binaries / 'docker'
    docker.write_text(f'#!{sys.executable}\n' + r'''
import json, os, sys
from pathlib import Path
import yaml
args = sys.argv[1:]
with open(os.environ['DOCKER_LOG'], 'a') as out:
    out.write(json.dumps((['docker-compose'] if Path(sys.argv[0]).name == 'docker-compose' else []) + args) + '\n')
standalone = Path(sys.argv[0]).name == 'docker-compose'
if standalone:
    args.insert(0, 'compose')
fail = os.environ.get('DEPLOY_TEST_FAILURE', '')
if args[0] == 'info':
    print('aarch64' if fail == 'architecture' else 'x86_64')
elif args[0] == 'load':
    sys.exit(1 if fail == 'load' else 0)
elif args[:2] == ['image', 'inspect']:
    print('linux/arm64' if fail == 'image_architecture' else 'linux/amd64')
elif args[0] == 'compose':
    if 'version' in args:
        if fail == 'plugin_missing' and not standalone:
            sys.exit(1)
        print('Docker Compose version v2.30.0')
    elif '--help' in args:
        print('--wait --wait-timeout --pull --no-build --images')
    elif 'config' in args:
        print('\n'.join(service['image'] for service in yaml.safe_load(Path(args[args.index('-f') + 1]).read_text())['services'].values()))
    elif 'up' in args:
        sys.exit(1 if fail == 'health' else 0)
    elif 'exec' in args:
        sys.exit(1 if (fail == 'http' and 'nginx' in args) or (fail == 'aidr_signer' and 'backend.aidr_signing' in args) else 0)
''')
    docker.chmod(0o755)
    shutil.copy2(docker, binaries / 'docker-compose')

    def run(action='start', archive=None, failure='', runner_root=None, extra_args=()):
        env = dict(os.environ, PATH=str(binaries),
                   DOCKER_LOG=str(log), DEPLOY_TEST_FAILURE=failure)
        # Any host Python invocation fails; the Docker double uses an absolute test interpreter.
        for name in ('python', 'python2', 'python3'):
            blocker = binaries / name
            blocker.write_text('#!/bin/sh\necho "host Python invoked" >&2\nexit 99\n')
            blocker.chmod(0o755)
        command = ['bash', str((runner_root or root) / f'{action}.sh')]
        if archive:
            command.append(str(archive))
        if runner_root:
            command += ['--install-dir', str(root)]
        command += ['--wait-timeout', '2', *extra_args]
        result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    return root, run


def test_start_loads_images_then_initializes_signer_and_waits(installation):
    root, run = installation
    original = (root / '.env').read_bytes()
    result, calls = run()
    assert result.returncode == 0, result.stderr
    load = next(i for i, call in enumerate(calls) if call[0] == 'load')
    signing = next(i for i, call in enumerate(calls) if 'signing-key' in call)
    up = next(i for i, call in enumerate(calls) if 'up' in call and '--help' not in call)
    assert load < signing < up
    assert '--wait' in calls[up] and '--wait-timeout' in calls[up]
    assert '--no-build' in calls[up] and calls[up][calls[up].index('--pull') + 1] == 'never'
    assert any('http://127.0.0.1/' in call for call in calls)
    assert any('backend.aidr_signing' in call and '--check' in call for call in calls)
    assert (root / '.env').read_bytes() == original
    assert '检查通过' in result.stdout


def test_start_creates_env_only_when_missing(installation):
    root, run = installation
    (root / '.env').unlink()
    result, _ = run()
    assert result.returncode == 0, result.stderr
    assert (root / '.env').read_bytes() == (root / '.env.example').read_bytes()
    assert (root / '.env').stat().st_mode & 0o777 == 0o600


def test_https_start_upgrade_and_switch_back(tmp_path, installation):
    root, run = installation
    result, calls = run(extra_args=('--https',))
    assert result.returncode == 0, result.stderr
    assert 'DEPLOY_PROTOCOL=https' in (root / '.env').read_text()
    assert any('--profile' in call and 'https' in call and 'up' in call for call in calls)
    assert any('https://127.0.0.1/' in call for call in calls)
    source = make_release(tmp_path / 'new')
    result, calls = run('upgrade', package(source, tmp_path / 'upgrade.tar.gz'))
    assert result.returncode == 0, result.stderr
    assert 'DEPLOY_PROTOCOL=https' in (root / '.env').read_text()
    result, calls = run()
    assert result.returncode == 0, result.stderr
    assert 'DEPLOY_PROTOCOL=http' in (root / '.env').read_text()
    assert any('stop' in call and 'certificates' in call for call in calls)


def test_source_start_uses_existing_images(installation):
    root, run = installation
    (root / 'release-info').unlink()
    (root / 'pyproject.toml').touch()
    (root / 'backend').mkdir()
    (root / 'backend/Dockerfile').touch()
    result, calls = run(extra_args=('--https',))
    assert result.returncode == 0, result.stderr
    assert not any(call[0] == 'load' for call in calls)
    assert any('up' in call and '--profile' in call for call in calls)


def test_start_and_upgrade_use_standalone_compose(tmp_path, installation):
    root, run = installation
    result, calls = run(failure='plugin_missing')
    assert result.returncode == 0, result.stdout + result.stderr
    assert any(call[0] == 'docker-compose' and 'up' in call for call in calls)
    source = make_release(tmp_path / 'new')
    result, calls = run('upgrade', package(source, tmp_path / 'upgrade.tar.gz'), failure='plugin_missing')
    assert result.returncode == 0, result.stdout + result.stderr
    assert any(call[0] == 'docker-compose' and '--force-recreate' in call for call in calls)


def test_custom_port_survives_restart_and_upgrade(tmp_path, installation, monkeypatch):
    root, run = installation
    original = (root / '.env').read_text()
    monkeypatch.setenv('HTTP_PORT', '9999')
    result, _ = run(extra_args=('--port', '18086'))
    assert result.returncode == 0, result.stderr
    expected = original + 'HTTP_PORT=18086\n'
    assert (root / '.env').read_text() == expected
    result, _ = run()
    assert result.returncode == 0, result.stderr
    assert (root / '.env').read_text() == expected
    source = make_release(tmp_path / 'new')
    result, _ = run('upgrade', package(source, tmp_path / 'release.tar.gz'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / '.env').read_text() == expected
    backup, = (root / 'backups').iterdir()
    assert (backup / '.env').read_text() == expected
    result, _ = run(extra_args=('--port=18087',))
    assert result.returncode == 0, result.stderr
    assert (root / '.env').read_text() == original + 'HTTP_PORT=18087\n'


@pytest.mark.parametrize('port', ['0', '65536', 'invalid'])
def test_invalid_port_does_not_change_installation(installation, port):
    root, run = installation
    original = (root / '.env').read_bytes()
    result, calls = run(extra_args=('--port', port))
    assert result.returncode != 0
    assert not calls
    assert (root / '.env').read_bytes() == original


def test_upgrade_backs_up_and_preserves_customer_env(tmp_path, installation):
    root, run = installation
    old_compose = (root / 'docker-compose.yaml').read_bytes()
    old_env = (root / '.env').read_bytes()
    old_nginx = (root / 'deploy/nginx/default.conf').read_bytes()
    source = make_release(tmp_path / 'new release')
    (source / 'deploy/nginx/default.conf').write_text('# new nginx config\n')
    archive = package(source, tmp_path / 'upgrade.tar.gz')
    result, calls = run('upgrade', archive, runner_root=source)
    assert result.returncode == 0, result.stdout + result.stderr
    backup, = (root / 'backups').iterdir()
    assert (backup / 'docker-compose.yaml').read_bytes() == old_compose
    assert (backup / '.env').read_bytes() == old_env
    assert (backup / 'deploy/nginx/default.conf').read_bytes() == old_nginx
    assert (root / '.env').read_bytes() == old_env
    assert (root / '.env').stat().st_mode & 0o777 == 0o600
    assert '1.0.7' in (root / 'docker-compose.yaml').read_text()
    assert '${TAG' not in (root / 'docker-compose.yaml').read_text()
    assert (root / 'deploy/nginx/default.conf').read_text() == '# new nginx config\n'
    assert json.loads((root / 'scanner/releases/latest.json').read_text())['version'] == '1.0.7'
    assert (root / 'docker_images/x86/agent-manager-images-1.0.6.tar.xz').exists()
    assert (root / 'docker_images/x86/agent-manager-images-1.0.7.tar.xz').exists()
    assert any('--force-recreate' in call for call in calls)
    assert all('down' not in call for call in calls)
    assert not list(root.glob('.upgrade-*'))
    assert backup.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize('failure', ['architecture', 'load', 'image_architecture', 'health', 'aidr_signer', 'http'])
def test_upgrade_failures_are_visible_and_keep_backups(tmp_path, installation, failure):
    root, run = installation
    original = (root / 'docker-compose.yaml').read_bytes()
    old_env = (root / '.env').read_bytes()
    source = make_release(tmp_path / 'new')
    result, calls = run('upgrade', package(source, tmp_path / 'release.tar.gz'), failure=failure)
    assert result.returncode != 0
    assert '已升级到' not in result.stdout
    assert (root / '.env').read_bytes() == old_env
    if failure == 'architecture':
        assert not (root / 'backups').exists()
        assert not any(call[0] == 'load' for call in calls)
    else:
        backup, = (root / 'backups').iterdir()
        assert (backup / 'docker-compose.yaml').read_bytes() == original
        assert str(backup) in result.stderr
    if failure in {'architecture', 'load', 'image_architecture'}:
        assert (root / 'docker-compose.yaml').read_bytes() == original
        assert not any('--force-recreate' in call for call in calls)
    else:
        assert '1.0.7' in (root / 'docker-compose.yaml').read_text()


@pytest.mark.parametrize('entry_type', ['escape', 'symlink', 'hardlink'])
def test_upgrade_rejects_archive_escape_before_touching_installation(tmp_path, installation, entry_type):
    root, run = installation
    original = (root / 'docker-compose.yaml').read_bytes()
    archive = tmp_path / 'unsafe.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        entry = tarfile.TarInfo('agent-manager/../../escaped' if entry_type == 'escape' else 'agent-manager/link')
        if entry_type != 'escape':
            entry.type = tarfile.SYMTYPE if entry_type == 'symlink' else tarfile.LNKTYPE
            entry.linkname = '../../escaped'
        bundle.addfile(entry, io.BytesIO())
    result, calls = run('upgrade', archive)
    assert result.returncode != 0
    assert '不安全路径' in result.stderr
    assert not calls
    assert not (tmp_path / 'escaped').exists()
    assert (root / 'docker-compose.yaml').read_bytes() == original


def test_start_refuses_another_operation_on_same_installation(installation):
    root, run = installation
    with (root / '.offline-deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, calls = run()
    assert result.returncode != 0
    assert '正在执行启动或升级' in result.stderr
    assert not calls


def test_upgrade_rejects_wrong_compose_version(tmp_path, installation):
    root, run = installation
    source = make_release(tmp_path / 'new')
    (source / 'docker-compose.yaml').write_text((ROOT / 'docker-compose.yaml').read_text())
    result, calls = run('upgrade', package(source, tmp_path / 'bad-version.tar.gz'))
    assert result.returncode != 0
    assert '镜像版本与安装包版本不一致' in result.stderr
    assert not any(call[0] == 'load' for call in calls)
    assert not (root / 'backups').exists()


@pytest.mark.parametrize('target_type', ['symlink', 'directory'])
def test_upgrade_rejects_unsafe_deployment_target(tmp_path, installation, target_type):
    root, run = installation
    original = (root / 'docker-compose.yaml').read_bytes()
    external = tmp_path / 'external.conf'
    external.write_text('site-managed config')
    nginx = root / 'deploy/nginx/default.conf'
    nginx.unlink()
    if target_type == 'symlink':
        nginx.symlink_to(external)
    else:
        nginx.mkdir()
    source = make_release(tmp_path / 'new')
    result, calls = run('upgrade', package(source, tmp_path / 'release.tar.gz'))
    assert result.returncode != 0
    assert ('软链接' if target_type == 'symlink' else '不是普通文件') in result.stderr
    assert external.read_text() == 'site-managed config'
    assert (root / 'docker-compose.yaml').read_bytes() == original
    assert not any('--force-recreate' in call for call in calls)


def test_upgrade_from_legacy_installation_using_new_script(tmp_path, installation):
    root, run = installation
    (root / 'release-info').unlink()
    (root / 'deploy/offline.sh').unlink()
    (root / 'upgrade.sh').write_text('#!/bin/bash\nexec python3 deploy/offline.py "$@"\n')
    original = (root / '.env').read_bytes()
    source = make_release(tmp_path / 'new')
    result, _ = run('upgrade', package(source, tmp_path / 'release.tar.gz'), runner_root=source)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / '.env').read_bytes() == original
    assert (root / 'release-info').read_text() == '1.0.7\nlinux/amd64\n'
    assert 'offline.sh' in (root / 'upgrade.sh').read_text()


@pytest.mark.parametrize('metadata', ['invalid version\nlinux/amd64\n', '1.0.7\nlinux/other\n',
                                       '1.0.7\n', '1.0.7\nlinux/amd64\nextra\n'])
def test_invalid_release_metadata_stops_before_docker(installation, metadata):
    root, run = installation
    (root / 'release-info').write_text(metadata)
    result, calls = run()
    assert result.returncode != 0
    assert '[ERROR]' in result.stderr
    assert not calls
