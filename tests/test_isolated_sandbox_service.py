import importlib.util
import base64
import sys
from pathlib import Path

import pytest


SERVICE_PATH = (
    Path(__file__).resolve().parents[1]
    / "services"
    / "isolated-sandbox-service"
    / "app.py"
)


def _load_service():
    spec = importlib.util.spec_from_file_location("isolated_sandbox_service_for_test", SERVICE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_secure_config_rejects_subprocess_backend():
    service = _load_service()
    config = service.ServiceConfig(
        backend="subprocess",
        api_key="sandbox-key-with-enough-entropy",
        enforce_secure_startup=True,
    )

    with pytest.raises(RuntimeError, match="BACKEND=nsjail"):
        config.validate_security()


@pytest.mark.parametrize("api_key", [None, "change-me", "sandbox-change-me"])
def test_secure_config_rejects_missing_or_placeholder_api_key(api_key):
    service = _load_service()
    config = service.ServiceConfig(
        backend="nsjail",
        api_key=api_key,
        enforce_secure_startup=True,
    )

    with pytest.raises(RuntimeError, match="API_KEY"):
        config.validate_security()


def test_nsjail_disables_network_by_default(tmp_path):
    service = _load_service()
    executor = service.NsjailExecutor(service.ServiceConfig())

    command = executor._build_nsjail_command(tmp_path, ["/usr/bin/python3", "/workspace/main.py"], False)

    assert "--iface_no_lo" in command
    assert "--disable_clone_newuser" in command
    assert "--no_pivotroot" in command
    assert "--chroot" in command
    assert "--bindmount_ro" in command
    assert "--tmpfsmount" in command
    assert "--rlimit_as" in command
    assert "--rlimit_cpu" in command


def test_workspace_snapshot_is_read_only_for_sandbox_user(tmp_path):
    service = _load_service()
    config = service.ServiceConfig(work_root=str(tmp_path))
    request = service.RunCodeRequest(language="python3", code="print('safe')")
    workspace = service.Workspace(config, request)
    try:
        source = workspace.prepare()
        assert workspace.root.stat().st_mode & 0o777 == 0o555
        assert source.stat().st_mode & 0o777 == 0o444
    finally:
        workspace.cleanup()


@pytest.mark.parametrize("path", ["../escape.py", "/etc/passwd"])
def test_workspace_rejects_path_escape(tmp_path, path):
    service = _load_service()
    config = service.ServiceConfig(work_root=str(tmp_path))
    request = service.RunCodeRequest(
        language="python3",
        code="print('safe')",
        files=[service.RunCodeFile(path=path, content="unsafe")],
    )
    workspace = service.Workspace(config, request)
    try:
        with pytest.raises(ValueError, match="Unsafe sandbox file path"):
            workspace.prepare()
    finally:
        workspace.cleanup()


def test_workspace_preserves_binary_file_bytes(tmp_path):
    service = _load_service()
    raw = b"\x80\x04\xff\x00\r\n"
    request = service.RunCodeRequest(language="python3", code="print('safe')", files=[
        service.RunCodeFile(path="fixtures/uploaded.pkl", content=base64.b64encode(raw).decode(), encoding="base64"),
        service.RunCodeFile(path="fixtures/text.txt", content="中文\r\n"),
    ])
    workspace = service.Workspace(service.ServiceConfig(work_root=str(tmp_path)), request)
    try:
        workspace.prepare()
        assert (workspace.root / "fixtures/uploaded.pkl").read_bytes() == raw
        assert (workspace.root / "fixtures/text.txt").read_bytes() == "中文\r\n".encode()
    finally:
        workspace.cleanup()


def test_binary_file_rejects_invalid_base64_before_workspace_creation():
    service = _load_service()
    with pytest.raises(ValueError):
        service.RunCodeFile(path="invalid.pkl", content="not base64!", encoding="base64")


@pytest.mark.parametrize("requested, expected", [(None, 15), (3, 3), (30, 15)])
def test_request_timeout_is_bounded_by_service_config(tmp_path, monkeypatch, requested, expected):
    service = _load_service()
    observed = []

    class Executor:
        def is_available(self):
            return True

        def execute(self, request):
            return service.RunCodeData(backend="nsjail")

    def executor(config):
        observed.append(config.default_timeout_seconds)
        return Executor()

    monkeypatch.setattr(service, "get_executor", executor)
    service.run_code(service.RunCodeRequest(language="python3", code="pass", timeout_seconds=requested),
                     service.ServiceConfig(work_root=str(tmp_path), default_timeout_seconds=15))
    assert observed == [expected]


def test_nsjail_timeout_is_reported_explicitly(tmp_path, monkeypatch):
    service = _load_service()

    def timed_out(*args, **kwargs):
        raise service.subprocess.TimeoutExpired(args[0], kwargs["timeout"], output=b"", stderr=b"timeout evidence")

    monkeypatch.setattr(service.subprocess, "run", timed_out)
    result = service.NsjailExecutor(service.ServiceConfig(work_root=str(tmp_path))).execute(
        service.RunCodeRequest(language="python3", code="pass"))
    assert result.timed_out is True
    assert result.stderr == "timeout evidence"
