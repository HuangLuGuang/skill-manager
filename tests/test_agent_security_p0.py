import json
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend import auth, models
from backend.api_errors import ApiError, api_error_handler
from backend.config import Settings, settings
from backend.feature_flags import (
    AGENT_SECURITY_AUDIT_EVENT_TYPES,
    ERROR_AGENT_SECURITY_FEATURE_DISABLED,
    ERROR_BASELINE_INVALID,
    ERROR_RUNTIME_TRACE_FEATURE_DISABLED,
    EXECUTION_MODES,
    FEATURE_AGENT_SECURITY_SCANNING,
    FEATURE_RUNTIME_TRACE,
    SCAN_TASK_STATUSES,
    TRACE_COMPLETENESS_VALUES,
    TRACE_EVENT_SOURCES,
    load_upstream_baseline,
)
from backend.routers import agent_security, system

LOCK_PATH = Path("deploy/agent-security/upstreams.lock.json")


def _client() -> TestClient:
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=1,
        username="admin",
        hashed_password="x",
        role="admin",
    )
    app.dependency_overrides[auth.get_current_active_user] = app.dependency_overrides[auth.get_current_admin_user]
    app.include_router(system.router, prefix="/api")
    app.include_router(
        agent_security.router,
        prefix="/api",
        dependencies=[Depends(auth.get_current_admin_user)],
    )
    return TestClient(app)


def test_feature_flags_are_enabled_by_default_without_compose_configuration():
    assert Settings.model_fields["AGENT_SECURITY_SCANNING_ENABLED"].default is True
    assert Settings.model_fields["RUNTIME_TRACE_ENABLED"].default is True
    compose = Path("docker-compose.yaml").read_text(encoding="utf-8")
    assert "AGENT_SECURITY_SCANNING_ENABLED:" not in compose
    assert "RUNTIME_TRACE_ENABLED:" not in compose


def test_capabilities_requires_an_authenticated_user():
    app = FastAPI()
    app.include_router(system.router, prefix="/api")
    with TestClient(app) as client:
        assert client.get("/api/system/capabilities").status_code == 401


def test_disabled_features_are_reported_and_baseline_apis_fail_closed(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_SECURITY_SCANNING_ENABLED", False)
    monkeypatch.setattr(settings, "RUNTIME_TRACE_ENABLED", False)
    client = _client()

    capabilities = client.get("/api/system/capabilities")
    scan_response = client.get("/api/v1/agent-security/baseline")
    trace_response = client.get("/api/v1/runtime-traces/baseline")

    assert capabilities.status_code == 200
    assert capabilities.json()["features"] == {
        FEATURE_AGENT_SECURITY_SCANNING: False,
        FEATURE_RUNTIME_TRACE: False,
    }
    assert scan_response.status_code == 404
    assert scan_response.json()["error_code"] == ERROR_AGENT_SECURITY_FEATURE_DISABLED
    assert scan_response.json()["error_params"] == {"feature": FEATURE_AGENT_SECURITY_SCANNING}
    assert trace_response.status_code == 404
    assert trace_response.json()["error_code"] == ERROR_RUNTIME_TRACE_FEATURE_DISABLED
    assert trace_response.json()["error_params"] == {"feature": FEATURE_RUNTIME_TRACE}


def test_enabled_features_expose_only_local_locked_baselines(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_SECURITY_SCANNING_ENABLED", True)
    monkeypatch.setattr(settings, "RUNTIME_TRACE_ENABLED", True)
    monkeypatch.setattr(settings, "AGENT_SECURITY_UPSTREAM_LOCK_PATH", str(LOCK_PATH))
    client = _client()

    scan_response = client.get("/api/v1/agent-security/baseline")
    trace_response = client.get("/api/v1/runtime-traces/baseline")

    assert scan_response.status_code == 200
    assert scan_response.json()["integration"]["tag"] == "v4.6.0"
    assert scan_response.json()["integration"]["commit"] == "e8931cc68001b66ad024fd87ef07394e9e96524a"
    assert scan_response.json()["runtime_source_fetch"] is False
    assert trace_response.status_code == 200
    assert trace_response.json()["integration"]["tag"] == "dsh-v0.1.2-alpha.1"
    assert trace_response.json()["integration"]["commit"] == "cd5ef8148158c3a752a658978873241fdf8e2bbc"
    assert trace_response.json()["integration"]["runtime_dependency"] is False


def test_upstream_lock_has_exact_versions_licenses_and_supported_scope():
    baseline = load_upstream_baseline(LOCK_PATH)
    aig = baseline["integrations"]["ai_infra_guard"]
    dsh = baseline["integrations"]["deepseek_harness"]

    assert baseline["policy"] == {
        "runtime_source_fetch": False,
        "offline_images_must_include_sources": True,
        "unlocked_ref_allowed": False,
    }
    assert aig["tag"] == "v4.6.0"
    assert len(aig["commit"]) == 40
    assert aig["license"]["spdx"] == "Apache-2.0"
    assert aig["license"]["notice_required"] is True
    assert aig["license"]["attribution"] == "Based on Tencent Zhuque Lab AI-Infra-Guard"
    assert {"dify", "coze", "openai", "anthropic", "google", "http", "websocket"}.issubset(
        set(aig["agent_scan"]["provider_types"])
    )
    assert len(aig["agent_scan"]["provider_catalog_sha256"]) == 64
    assert len(aig["agent_scan"]["adapter_sha256"]) == 64
    assert {item["component"] for item in aig["reuse"]} == {"agent-scan", "mcp-scan", "full-service"}
    full_service = next(item for item in aig["reuse"] if item["component"] == "full-service")
    assert full_service["mode"] == "authenticated_internal_service_source"
    assert len(full_service["vendored_tree_sha256"]) == 64
    assert all({"code", "zh-CN", "en-US"}.issubset(item) for item in aig["known_limitations"])
    assert dsh["tag"] == "dsh-v0.1.2-alpha.1"
    assert len(dsh["commit"]) == 40
    assert dsh["license"]["spdx"] == "MIT"
    assert dsh["runtime_dependency"] is False
    assert all(item["mode"] == "design_reference_only" for item in dsh["reuse"])
    assert set(dsh["reference_files"]) == set(dsh["reference_file_sha256"])
    assert all(len(value) == 64 for value in dsh["reference_file_sha256"].values())
    assert all({"code", "zh-CN", "en-US"}.issubset(item) for item in dsh["known_limitations"])


def test_invalid_lock_is_rejected_with_stable_error(tmp_path):
    invalid_path = tmp_path / "upstreams.lock.json"
    payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    payload["policy"]["runtime_source_fetch"] = True
    invalid_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        load_upstream_baseline(invalid_path)
        raise AssertionError("invalid baseline was accepted")
    except ApiError as exc:
        assert exc.code == ERROR_BASELINE_INVALID
        assert exc.status_code == 500


def test_p0_stable_code_sets_are_unique_and_complete():
    all_values = (
        *SCAN_TASK_STATUSES,
        *TRACE_COMPLETENESS_VALUES,
        *EXECUTION_MODES,
        *TRACE_EVENT_SOURCES,
        *AGENT_SECURITY_AUDIT_EVENT_TYPES,
    )
    assert len(all_values) == len(set(all_values))
    assert TRACE_COMPLETENESS_VALUES == ("full", "gateway_partial", "model_only", "mcp_only")
    assert EXECUTION_MODES == ("passive", "read_only", "active_safe", "active_full")
    assert "runtime_trace.raw_payload_viewed" in AGENT_SECURITY_AUDIT_EVENT_TYPES


def test_p0_runtime_uses_packaged_lock_and_declares_no_source_fetch():
    dockerfile = Path("backend/Dockerfile").read_text(encoding="utf-8")
    compose = Path("docker-compose.yaml").read_text(encoding="utf-8")
    runtime_modules = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in ("backend/feature_flags.py", "backend/routers/agent_security.py")
    )

    assert "COPY deploy/agent-security ./deploy/agent-security" in dockerfile
    assert "AGENT_SECURITY_UPSTREAM_LOCK_PATH: /app/deploy/agent-security/upstreams.lock.json" in compose
    assert 'runtime_source_fetch": false' in LOCK_PATH.read_text(encoding="utf-8")
    assert "git clone" not in runtime_modules
    assert "import requests" not in runtime_modules
    assert "import httpx" not in runtime_modules
    assert "import urllib.request" not in runtime_modules
    assert "import subprocess" not in runtime_modules
