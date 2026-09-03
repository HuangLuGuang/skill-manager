from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


WORKER_DIR = Path("services/agent-security-worker").resolve()
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from ai_infrastructure_adapter import execute_infrastructure_scan, normalize_infrastructure_result  # noqa: E402


def _claim():
    return {
        "task": {"task_id": "asj_infra_test"},
        "target": {
            "endpoint_url": "https://ollama.example",
            "config": {
                "endpoints": ["https://ollama.example", "https://unknown.example"],
                "headers": {"X-Tenant": "security-test"},
                "timeout_ms": 15000,
            },
        },
        "policy": {"task_timeout_seconds": 30, "max_duration_seconds": 30},
        "scan_options": {"scan_concurrency": 2, "scan_timeout_seconds": 15},
    }


def _raw():
    return {
        "total": 1,
        "score": 70,
        "results": [
            {
                "target_url": "https://ollama.example",
                "status_code": 200,
                "fingerprint": "Ollama 0.1.32",
                "vulnerabilities": [
                    {
                        "name": "Ollama",
                        "cve": "CVE-2024-0001",
                        "summary": "Version-specific test advisory",
                        "details": "Affected version matched by the engine rule.",
                        "cvss": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                        "severity": "high",
                        "security_advise": "Upgrade",
                        "references": ["https://advisories.example/CVE-2024-0001"],
                    }
                ],
            },
            {
                "target_url": "https://unknown.example",
                "status_code": 200,
                "fingerprint": "Unknown AI service",
                "vulnerabilities": [],
            },
        ],
    }


def test_infrastructure_normalization_requires_version_evidence_for_cve_and_marks_unknown_unverified():
    result = normalize_infrastructure_result(
        claim=_claim(), raw_result=_raw(), session_id="infra-session", initial_usage={}
    )
    assert [item["status"] for item in result["cases"]] == ["failed", "unverified"]
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["case_external_id"] == "aig-infra-endpoint:1"
    assert finding["finding_code"] == "CVE-2024-0001"
    assert finding["evidence"]["component"] == "Ollama"
    assert finding["evidence"]["component_version"] == "0.1.32"
    assert finding["evidence"]["affected_version_match"] is True
    assert result["cases"][1]["response_summary"]["assessment_status"] == "unverified"


def test_infrastructure_vulnerability_without_observed_version_is_not_confirmed():
    raw = _raw()
    raw["results"][0]["fingerprint"] = "Ollama"
    result = normalize_infrastructure_result(
        claim=_claim(), raw_result=raw, session_id="infra-session", initial_usage={}
    )
    assert result["cases"][0]["status"] == "unverified"
    assert result["findings"] == []


class _Client:
    def __init__(self):
        self.created = []

    def create_task(self, **kwargs):
        self.created.append(kwargs)
        return "infra-session"

    def get_status(self, _session_id):
        return {"session_id": "infra-session", "status": "done"}

    def get_result(self, _session_id):
        return _raw()

    def cancel_task(self, _session_id):
        raise AssertionError("cancel not expected")


def test_infrastructure_execute_passes_only_explicit_urls_and_controlled_headers():
    client = _Client()
    result = execute_infrastructure_scan(
        _claim(),
        "short-lived-target-secret",
        SimpleNamespace(api_key="eval-secret", model="eval-model", base_url="https://gateway/v1"),
        lambda *_args: {"continue_allowed": True},
        initial_usage={"rounds": 5, "tokens": 10, "cost_microunits": 0, "concurrent_requests": 1, "response_bytes": 20},
        client=client,
    )
    content = client.created[0]["content"]
    assert content["target"] == ["https://ollama.example", "https://unknown.example"]
    assert content["headers"]["X-Tenant"] == "security-test"
    assert content["headers"]["Authorization"] == "Bearer short-lived-target-secret"
    assert content["timeout"] == 15
    assert result["usage"]["rounds"] == 7
    assert result["usage"]["concurrent_requests"] == 2
    assert "short-lived-target-secret" not in str(result)


def test_infrastructure_missing_endpoint_result_is_execution_error_not_safe():
    raw = _raw()
    raw["results"] = raw["results"][:1]
    result = normalize_infrastructure_result(
        claim=_claim(), raw_result=raw, session_id="infra-session", initial_usage={}
    )
    assert result["cases"][1]["status"] == "error"
    assert result["cases"][1]["response_summary"]["assessment_status"] == "unverified"
