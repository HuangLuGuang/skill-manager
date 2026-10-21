"""Exercise the Bash runtime diagnostics with fake Docker executables."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy/offline.sh'
pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='Deployment targets Linux system tools')


def check(tmp_path, *, error='', plugin='ok', standalone='missing'):
    binary = tmp_path / 'docker'
    binary.write_text('''#!/bin/bash
if [[ $1 == info ]]; then
    [[ -z $INFO_ERROR ]] || { echo "$INFO_ERROR" >&2; exit 1; }
    echo amd64; exit
fi
mode=$PLUGIN
[[ ${0##*/} != docker-compose ]] || mode=$STANDALONE
[[ $mode != missing ]] || exit 1
if [[ $mode == ok ]]; then echo '--wait --wait-timeout --images'; else echo '--wait-timeout'; fi
''')
    binary.chmod(0o755)
    (tmp_path / 'docker-compose').symlink_to(binary)
    return subprocess.run(
        ['bash', '-c', 'source "$1"; check_runtime; echo "${COMPOSE_COMMAND[*]}"', 'test', str(SCRIPT)],
        env=dict(os.environ, PATH=f'{tmp_path}:{os.environ["PATH"]}', INFO_ERROR=error,
                 PLUGIN=plugin, STANDALONE=standalone), capture_output=True, text=True,
    )


@pytest.mark.parametrize(('error', 'expected'), [
    ('dial unix: permission denied', '当前用户无权访问 Docker'),
    ('Cannot connect to the Docker daemon', '服务可能未启动'),
    ('x509 invalid certificate credential-do-not-print', 'TLS 或认证配置'),
])
def test_docker_errors(tmp_path, error, expected):
    result = check(tmp_path, error=error)
    assert result.returncode != 0
    assert expected in result.stderr
    assert 'credential-do-not-print' not in result.stderr


@pytest.mark.parametrize(('plugin', 'standalone', 'expected'), [
    ('ok', 'ok', 'docker compose'),
    ('missing', 'ok', 'docker-compose'),
    ('old', 'ok', 'docker-compose'),
    ('missing', 'missing', '均不可用'),
    ('missing', 'old', 'Compose 版本不兼容'),
])
def test_compose_selection(tmp_path, plugin, standalone, expected):
    result = check(tmp_path, plugin=plugin, standalone=standalone)
    assert (result.returncode == 0) == ('ok' in (plugin, standalone))
    assert expected in result.stdout + result.stderr


def test_missing_docker(tmp_path):
    result = subprocess.run(
        ['/bin/bash', '-c', 'source "$1"; check_runtime', 'test', str(SCRIPT)],
        env=dict(os.environ, PATH=str(tmp_path)), capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert 'Docker 未安装或未加入 PATH' in result.stderr


def test_probe_timeout(tmp_path):
    timeout = tmp_path / 'timeout'
    timeout.write_text('#!/bin/bash\nexit 124\n')
    timeout.chmod(0o755)
    result = check(tmp_path)
    assert result.returncode != 0
    assert '超时' in result.stderr
