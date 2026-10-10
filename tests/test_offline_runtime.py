"""Dependency diagnostics, also runnable with the deployment host's stdlib Python."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('offline', Path(__file__).resolve().parents[1] / 'deploy/offline.py')
offline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(offline)


class RuntimeChecks(unittest.TestCase):
    def check(self, *, info_error='', plugin='ok', standalone=None):
        def which(name):
            return '/bin/' + name if name == 'docker' or standalone is not None else None

        def execute(args, **kwargs):
            if args[1] == 'info':
                return subprocess.CompletedProcess(args, int(bool(info_error)), 'amd64' if not info_error else '', info_error)
            mode = standalone if args[0] == 'docker-compose' else plugin
            if mode == 'missing':
                return subprocess.CompletedProcess(args, 1, '', 'command not found')
            output = '--wait --wait-timeout --format' if mode == 'ok' else '--wait-timeout'
            return subprocess.CompletedProcess(args, 0, output, '')

        with patch.object(offline.shutil, 'which', side_effect=which), patch.object(offline.subprocess, 'run', side_effect=execute):
            return offline.check_runtime()

    def test_missing_docker(self):
        with patch.object(offline.shutil, 'which', return_value=None), patch.object(offline.subprocess, 'run') as run:
            with self.assertRaisesRegex(offline.DeploymentError, 'Docker 未安装或未加入 PATH'):
                offline.check_runtime()
            run.assert_not_called()

    def test_docker_permission_denied(self):
        with self.assertRaisesRegex(offline.DeploymentError, '当前用户无权访问 Docker'):
            self.check(info_error='dial unix /var/run/docker.sock: connect: permission denied')

    def test_daemon_unreachable(self):
        with self.assertRaisesRegex(offline.DeploymentError, '服务可能未启动.*context/DOCKER_HOST'):
            self.check(info_error='Cannot connect to the Docker daemon. Is the docker daemon running?')

    def test_other_connection_errors_are_not_mislabeled(self):
        with self.assertRaisesRegex(offline.DeploymentError, 'TLS 或认证配置') as result:
            self.check(info_error='x509 invalid certificate credential-do-not-print')
        self.assertNotIn('credential-do-not-print', str(result.exception))

    def test_missing_compose(self):
        with self.assertRaisesRegex(offline.DeploymentError, '均不可用'):
            self.check(plugin='missing')

    def test_old_compose(self):
        with self.assertRaisesRegex(offline.DeploymentError, 'Compose 版本不兼容'):
            self.check(plugin='missing', standalone='old')

    def test_plugin_preferred(self):
        self.assertEqual(self.check(standalone='ok'), ('amd64', ('docker', 'compose')))

    def test_standalone_selected(self):
        self.assertEqual(self.check(plugin='missing', standalone='ok'), ('amd64', ('docker-compose',)))

    def test_incompatible_plugin_uses_capable_standalone(self):
        self.assertEqual(self.check(plugin='old', standalone='ok'), ('amd64', ('docker-compose',)))

    def test_timeout(self):
        with patch.object(offline.subprocess, 'run', side_effect=subprocess.TimeoutExpired('docker', 20)):
            with self.assertRaisesRegex(offline.DeploymentError, '超时'):
                offline.probe(['docker', 'info'])


if __name__ == '__main__':
    unittest.main()
