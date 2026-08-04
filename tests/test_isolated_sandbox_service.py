import importlib.util
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
