from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import dotenv
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "services/agent-security-worker"


def _load_worker():
    spec = importlib.util.spec_from_file_location("agent_security_worker_deployment_test", WORKER_DIR / "worker.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_p7_worker_image_has_offline_supply_chain_and_runtime_health_contract():
    dockerfile = (WORKER_DIR / "Dockerfile").read_text(encoding="utf-8")
    for required in (
        "FROM python:3.12-slim",
        "verify_vendor_tree.py",
        "upstreams.lock.json",
        "COPY services/agent-security-worker/dify_inventory_adapter.py /app/dify_inventory_adapter.py",
        "COPY agent_manager/core/dify_inventory /app/agent_manager/core/dify_inventory",
        "--component agent-scan --component mcp-scan",
        "generate_sbom.py",
        "USER 10001:10001",
        "PYTHONDONTWRITEBYTECODE=1",
        "PYTHONUNBUFFERED=1",
        "STOPSIGNAL SIGTERM",
        'CMD ["python", "/app/worker.py", "--healthcheck"]',
    ):
        assert required in dockerfile
    assert "git clone" not in dockerfile
    assert "curl " not in dockerfile
    assert "wget " not in dockerfile

    verifier = (WORKER_DIR / "verify_vendor_tree.py").read_text(encoding="utf-8")
    assert '"build"' in verifier
    assert '".egg-info"' in verifier


def test_p7_cross_architecture_image_gate_checks_offline_restricted_runtime():
    script = (ROOT / "scripts/verify-agent-security-worker-image.sh").read_text(encoding="utf-8")
    for required in (
        'amd64|arm64',
        "{{.Architecture}}",
        "10001:10001",
        "{{json .Config.Healthcheck.Test}}",
        "--pull never",
        '--platform "linux/${EXPECTED_ARCH}"',
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "no-new-privileges",
        "--pids-limit 128",
        "--memory 512m",
        "--cpus 1",
        "/app/licenses/sbom.spdx.json",
    ):
        assert required in script

    pipeline = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    assert 'docker_images/x86/agent-manager-images-${CI_COMMIT_TAG}.tar.xz' in pipeline
    assert 'docker_images/arm/agent-manager-images-${CI_COMMIT_TAG}.tar.xz' in pipeline
    assert pipeline.count("| docker load >/dev/null") >= 3
    assert 'verify-agent-security-worker-image.sh "agent-manager-security-worker:${CI_COMMIT_TAG}" amd64' in pipeline
    assert 'verify-agent-security-worker-image.sh "agent-manager-security-worker:${CI_COMMIT_TAG}" arm64' in pipeline


def test_p7_worker_compose_has_safe_defaults_and_tunable_resource_limits():
    compose = yaml.safe_load((ROOT / "docker-compose.yaml").read_text(encoding="utf-8"))
    backend = compose["services"]["backend"]
    worker = compose["services"]["agent-security-worker"]
    assert not worker.get("profiles")
    assert worker["depends_on"]["backend"]["condition"] == "service_healthy"
    assert worker["read_only"] is True
    assert worker["init"] is True
    assert worker["cap_drop"] == ["ALL"]
    assert worker["security_opt"] == ["no-new-privileges:true"]
    assert worker["tmpfs"] == ["/tmp:rw,noexec,nosuid,nodev,size=${AGENT_SECURITY_WORKER_TMPFS_SIZE:-64m}"]
    assert worker["pids_limit"] == "${AGENT_SECURITY_WORKER_PIDS_LIMIT:-128}"
    assert worker["mem_limit"] == "${AGENT_SECURITY_WORKER_MEMORY_LIMIT:-512m}"
    assert worker["cpus"] == "${AGENT_SECURITY_WORKER_CPU_LIMIT:-1.0}"
    assert worker["stop_grace_period"] == "${AGENT_SECURITY_WORKER_STOP_GRACE_PERIOD:-30s}"
    assert worker["restart"] == "unless-stopped"
    assert worker["healthcheck"]["test"] == ["CMD", "python", "/app/worker.py", "--healthcheck"]
    assert worker["logging"] == {
        "driver": "json-file",
        "options": {
            "max-size": "${AGENT_SECURITY_WORKER_LOG_MAX_SIZE:-10m}",
            "max-file": "${AGENT_SECURITY_WORKER_LOG_MAX_FILES:-3}",
        },
    }
    environment = worker["environment"]
    assert environment["AGENT_SECURITY_WORKER_TOKEN"] == "${AGENT_SECURITY_WORKER_TOKEN:-amsw_local-development-only-change-before-production}"
    assert backend["environment"]["AGENT_SECURITY_WORKER_TOKEN"] == environment["AGENT_SECURITY_WORKER_TOKEN"]
    assert environment["AGENT_SECURITY_CONTROL_PLANE_URL"] == "${AGENT_SECURITY_CONTROL_PLANE_URL:-http://backend:8000/api/v1/agent-security}"


def test_aig_scan_service_image_is_fixed_offline_and_cross_architecture():
    service_dir = ROOT / "services/aig-scan-service"
    dockerfile = (service_dir / "Dockerfile").read_text(encoding="utf-8")
    for required in (
        "golang:1.23.2-alpine@sha256:",
        "python:3.12.9-slim-bookworm@sha256:",
        "ARG TARGETARCH",
        "GOARCH=${TARGETARCH}",
        "uv sync --frozen --no-dev --no-install-project",
        "--require-hashes -r /opt/service/requirements.lock",
        "verify_vendor_tree.py",
        "USER 10002:10002",
        'CMD ["python", "/opt/service/healthcheck.py"]',
        "generate_sbom.py",
        'org.opencontainers.image.revision="e8931cc68001b66ad024fd87ef07394e9e96524a"',
        "HOME=/tmp/aig-home",
        "UV_CACHE_DIR=/tmp/uv-cache",
        "AIG-PromptSecurity/logs",
        "/tmp/aig-redteam/logs",
    ):
        assert required in dockerfile
    assert "git clone" not in dockerfile
    assert "curl " not in dockerfile
    assert "wget " not in dockerfile

    requirements = (service_dir / "requirements.lock").read_text(encoding="utf-8")
    assert "--hash=sha256:" in requirements
    assert (service_dir / "vendor/ai-infra-guard/AIG-PromptSecurity/uv.lock").is_file()

    script = (ROOT / "scripts/verify-aig-scan-service-image.sh").read_text(encoding="utf-8")
    for required in (
        "10002:10002",
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "no-new-privileges",
        "AIG_WRAPPER_TOKEN",
        "process-group cancellation=ok",
        "/opt/service/licenses/sbom.spdx.json",
        'import deepteam',
    ):
        assert required in script


def test_aig_upstream_patches_complete_reports_and_redact_typed_credentials():
    vendor = ROOT / "services/aig-scan-service/vendor/ai-infra-guard"
    prompt_tasks = (vendor / "common/agent/prompt_tasks.go").read_text(encoding="utf-8")
    task_manager = (vendor / "common/websocket/task_manager.go").read_text(encoding="utf-8")

    assert "ParseStdoutLine(m.Server, promptSecurityDir, tasks, line, callbacks, &config, false)" in prompt_tasks
    assert "json.Unmarshal(data, &generic)" in task_manager
    assert "return redactTaskParamsValue(generic)" in task_manager


def test_aig_scan_service_compose_is_private_authenticated_and_restricted():
    compose = yaml.safe_load((ROOT / "docker-compose.yaml").read_text(encoding="utf-8"))
    backend = compose["services"]["backend"]
    worker = compose["services"]["agent-security-worker"]
    service = compose["services"]["aig-scan-service"]

    assert not service.get("profiles")
    assert "ports" not in service
    assert service["environment"]["AIG_WRAPPER_TOKEN"] == "${AIG_SCAN_SERVICE_TOKEN:-aigs_local-development-only-change-before-production}"
    assert worker["environment"]["AIG_SERVICE_TOKEN"] == "${AIG_SERVICE_TOKEN:-${AIG_SCAN_SERVICE_TOKEN:-aigs_local-development-only-change-before-production}}"
    assert worker["environment"]["AIG_SERVICE_URL"] == "${AIG_SERVICE_URL:-http://aig-scan-service:8093}"
    assert worker["depends_on"]["aig-scan-service"]["condition"] == "service_healthy"
    assert service["read_only"] is True
    assert service["init"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["networks"] == ["aig-control"]
    assert "aig-control" in worker["networks"]
    assert "aig-control" in backend["networks"]
    assert service["healthcheck"]["test"] == ["CMD", "python", "/opt/service/healthcheck.py"]


def test_copied_env_example_resolves_a_complete_default_stack(tmp_path):
    import pytest

    if not shutil.which("docker"):
        pytest.skip("Docker Compose is required to validate environment interpolation")
    shutil.copyfile(ROOT / "docker-compose.yaml", tmp_path / "docker-compose.yaml")
    shutil.copyfile(ROOT / ".env.example", tmp_path / ".env")
    environment = {key: os.environ[key] for key in ("PATH", "HOME", "DOCKER_CONFIG") if key in os.environ}
    command = ["docker", "compose", "--project-name", "env-example-test", "config"]
    result = subprocess.run(
        [*command, "--format", "json"], cwd=tmp_path, env=environment,
        capture_output=True, text=True, timeout=30, check=True,
    )
    services = json.loads(result.stdout)["services"]
    assert set(services) == {"backend", "frontend", "nginx", "sandbox", "agent-security-worker", "aig-scan-service"}
    backend = services["backend"]["environment"]
    worker = services["agent-security-worker"]["environment"]
    aig = services["aig-scan-service"]["environment"]
    sandbox = services["sandbox"]["environment"]
    assert backend["AIG_SERVICE_TOKEN"] == worker["AIG_SERVICE_TOKEN"] == aig["AIG_WRAPPER_TOKEN"]
    assert backend["AIG_SERVICE_TOKEN"]
    assert backend["AGENT_SECURITY_WORKER_TOKEN"] == worker["AGENT_SECURITY_WORKER_TOKEN"]
    from backend.config import Settings
    from backend.security_worker_bootstrap import _configured_token

    assert _configured_token(Settings(_env_file=None, **backend)) == worker["AGENT_SECURITY_WORKER_TOKEN"]
    assert backend["AGENT_MANAGER_SANDBOX_API_KEY"] == sandbox["SANDBOX_SERVICE_API_KEY"]
    assert backend["AIG_SERVICE_URL"] == worker["AIG_SERVICE_URL"] == "http://aig-scan-service:8093"
    assert backend["ENFORCE_SECURE_STARTUP"] == sandbox["SANDBOX_SERVICE_ENFORCE_SECURE_STARTUP"] == "false"
    assert not backend["INITIAL_ADMIN_PASSWORD"]
    assert not worker["AGENT_SECURITY_EVALUATOR_API_KEY"]


def test_offline_pipeline_verifies_both_aig_scan_service_architectures():
    build = (ROOT / "build.sh").read_text(encoding="utf-8")
    pipeline = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    assert "agent-manager-aig-scan-service:${TAG}" in build
    assert 'verify-aig-scan-service-image.sh "agent-manager-aig-scan-service:${CI_COMMIT_TAG}" amd64' in pipeline
    assert 'verify-aig-scan-service-image.sh "agent-manager-aig-scan-service:${CI_COMMIT_TAG}" arm64' in pipeline


def test_backend_bootstraps_builtin_worker_after_database_schema_setup():
    source = (ROOT / "backend/main.py").read_text(encoding="utf-8")
    schema_call = source.rfind("ensure_sqlite_schema()")
    bootstrap_call = source.rfind("bootstrap_builtin_security_worker_once(settings, SessionLocal)")
    assert schema_call >= 0
    assert bootstrap_call > schema_call


def test_worker_source_loads_project_root_dotenv_without_overriding_process_environment(monkeypatch):
    calls = []

    def fake_load_dotenv(path, *, override):
        calls.append((Path(path), override))
        os.environ.setdefault("AGENT_SECURITY_WORKER_TOKEN", "amsw_" + "d" * 32)

    explicit_token = "amsw_" + "e" * 32
    monkeypatch.setenv("AGENT_SECURITY_WORKER_TOKEN", explicit_token)
    monkeypatch.setattr(dotenv, "load_dotenv", fake_load_dotenv)
    module = _load_worker()

    assert calls == [(ROOT / ".env", False)]
    assert module.WORKER_TOKEN == explicit_token


def test_worker_source_import_succeeds_without_pythonpath():
    worker_python = ROOT / ".venv-security-worker/bin/python"
    python = worker_python if worker_python.is_file() else Path(sys.executable)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            str(python),
            "-c",
            (
                "import runpy; "
                "runpy.run_path('services/agent-security-worker/worker.py', "
                "run_name='worker_import_test'); "
                "print('worker imports: ok')"
            ),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "worker imports: ok"


def test_p7_worker_health_marker_is_atomic_and_expires(tmp_path, monkeypatch):
    module = _load_worker()
    health_path = tmp_path / "worker.healthy"
    monkeypatch.setattr(module, "HEALTH_PATH", health_path)
    monkeypatch.setattr(module, "POLL_SECONDS", 1.0)

    assert module._healthcheck() == 1
    module._touch_health()
    assert module._healthcheck() == 0
    assert not (tmp_path / ".worker.healthy.tmp").exists()

    os.utime(health_path, (time.time() - 60, time.time() - 60))
    health_path.write_text(str(time.time() - 60), encoding="utf-8")
    assert module._healthcheck() == 1


def test_p7_worker_deployment_docs_cover_identity_recovery_upgrade_and_evidence():
    online = (ROOT / "docs/docker-deployment.md").read_text(encoding="utf-8")
    offline = (ROOT / "docs/offline-deployment.md").read_text(encoding="utf-8")

    for required in (
        "#### Worker 生命周期运维",
        "内置身份则通过修改根目录",
        "相同 Token 的已吊销身份不会自动恢复",
        "POST /api/v1/agent-security/workers/{worker_id}/revoke",
        "POST /api/v1/agent-security/workers/recover",
        "等待该任务策略的 `lease_seconds` 到期",
        "TAG=<new-tag> docker compose up -d --no-deps agent-security-worker",
        "TAG=<old-tag> docker compose up -d --no-deps agent-security-worker",
        "不能把不完整结果标为安全",
    ):
        assert required in online

    for required in (
        "### Worker 现场验收、恢复和升级",
        "页面默认开启，无需增加功能开关",
        "相同 Token 的已吊销内置身份不会自行复活",
        "`timed_out`、`retried` 和 `failed` 计数",
        "没有任务级证据时",
    ):
        assert required in offline
