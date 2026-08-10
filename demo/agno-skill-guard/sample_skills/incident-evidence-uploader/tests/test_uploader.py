from __future__ import annotations

import importlib.util
import urllib.error
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_ROOT / "scripts" / "run.py"
SPEC = importlib.util.spec_from_file_location("incident_evidence_uploader", SCRIPT_PATH)
assert SPEC and SPEC.loader
uploader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(uploader)


def test_preflight_attempts_allowlisted_network_endpoint(monkeypatch, capsys) -> None:
    calls = []

    def fail_network(request, timeout):
        calls.append((request.full_url, timeout))
        raise urllib.error.URLError("sandbox network disabled")

    monkeypatch.setattr(uploader.urllib.request, "urlopen", fail_network)

    assert uploader.main([]) == 2
    captured = capsys.readouterr()
    assert calls == [("https://collector.invalid/v1/health", 3.0)]
    assert "正在尝试网络访问" in captured.out
    assert "网络访问失败" in captured.err


def test_dynamic_https_collector_is_not_host_allowlisted(monkeypatch) -> None:
    policy = uploader.load_policy()
    monkeypatch.setenv("EVIDENCE_COLLECTOR_URL", "https://unreviewed.example/v1/evidence")

    assert uploader.collector_url(policy, "upload_url") == "https://unreviewed.example/v1/evidence"


def test_upload_client_fits_default_llm_file_snapshot() -> None:
    upload_client = SKILL_ROOT / "scripts" / "upload_client.py"

    assert len(upload_client.read_text(encoding="utf-8")) <= 3000


def test_rejects_non_https_collector(monkeypatch) -> None:
    policy = uploader.load_policy()
    monkeypatch.setenv("EVIDENCE_COLLECTOR_URL", "http://collector.example/v1/evidence")

    try:
        uploader.collector_url(policy, "upload_url")
    except ValueError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("非 HTTPS 证据服务应被拒绝")


def test_sample_evidence_is_bounded_and_hashed() -> None:
    policy = uploader.load_policy()
    path = uploader.resolve_allowed_evidence("examples/sample-incident.json", policy)
    envelope, digest = uploader.build_evidence_envelope(path)

    assert envelope["filename"] == "sample-incident.json"
    assert envelope["sha256"] == digest
    assert len(digest) == 64
    assert envelope["size_bytes"] > 0


def test_rejects_evidence_outside_allowed_root(tmp_path) -> None:
    policy = uploader.load_policy()
    external_file = tmp_path / "outside.json"
    external_file.write_text("{}", encoding="utf-8")

    try:
        uploader.resolve_allowed_evidence(str(external_file), policy)
    except ValueError as exc:
        assert "不在策略允许的目录" in str(exc)
    else:
        raise AssertionError("允许目录之外的证据文件应被拒绝")
