from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_manager.api import router as api_router
from agent_manager.core.policy import CompanyPolicy, DEFAULT_RISK_CLASSIFICATION
from agent_manager.core.policy_simulation import PolicySimulationRequest, simulate_policy


def example():
    return {
        "policy": {},
        "rules": {"status": "completed", "findings": [{"kind": "dynamic_execution", "severity": "MEDIUM"}]},
        "deep": {"status": "completed", "findings": []},
        "sandbox": {"status": "completed", "findings": []},
        "llm": {"status": "completed", "risk": "benign"},
    }


def calculate(body):
    return simulate_policy(PolicySimulationRequest.model_validate(body))


@pytest.mark.parametrize("mode, risk, action, reason", [
    ("balanced", "benign", "APPROVED", "lowered"),
    ("strict", "suspicious", "VETTED", "blocked_by_mode"),
    ("permissive", "benign", "APPROVED", "unchanged"),
])
def test_contextual_finding_and_llm_mode(mode, risk, action, reason):
    body = example()
    body["policy"]["judgement_mode"] = mode
    result = calculate(body)
    assert (result["final_risk"], result["admission_status"], result["llm_reason"]) == (risk, action, reason)


@pytest.mark.parametrize("mode", ["strict", "balanced", "permissive"])
def test_blocking_evidence_retains_risk_and_obeys_admission_action(mode):
    body = example()
    body["rules"]["findings"] = [{"kind": "data_exfiltration", "severity": "LOW"}]
    body["policy"] = {"risk_classification": {"data_exfiltration": "blocking"}, "judgement_mode": mode, "auto_reject_risk": [], "require_human_review": ["malicious"]}
    result = calculate(body)
    assert result["final_risk"] == "malicious"
    assert result["llm_reason"] == "blocked_by_finding"
    assert result["admission_status"] == "VETTED"


@pytest.mark.parametrize("kind", DEFAULT_RISK_CLASSIFICATION)
@pytest.mark.parametrize("classification, risk", [("blocking", "malicious"), ("risk", "suspicious"), ("noise", "benign")])
def test_every_selectable_finding_uses_real_classification_override(kind, classification, risk):
    body = example()
    body["rules"]["findings"] = [{"kind": kind, "severity": "HIGH"}]
    body["llm"]["status"] = "disabled"
    body["policy"]["risk_classification"] = {kind: classification}
    result = calculate(body)
    assert result["findings"][0]["classification"] == classification
    assert result["final_risk"] == risk


def test_llm_raises_risk_when_tools_have_no_findings():
    body = example()
    body["rules"]["findings"] = []
    body["llm"]["risk"] = "malicious"
    result = calculate(body)
    assert result["tool_risk"] == "benign"
    assert result["final_risk"] == "malicious"
    assert result["llm_reason"] == "raised"


@pytest.mark.parametrize("status", ["disabled", "skipped", "unavailable", "failed"])
def test_inactive_inputs_do_not_contribute_and_are_distinct_from_empty_completed(status):
    body = example()
    for source in ("rules", "deep", "sandbox", "llm"):
        body[source]["status"] = status
    body["rules"]["findings"] = [{"kind": "data_exfiltration", "severity": "CRITICAL"}]
    body["llm"]["risk"] = "malicious"
    result = calculate(body)
    assert result["findings"] == []
    assert result["llm_risk"] is None
    assert result["llm_reason"] == status
    assert result["coverage"] == "none"
    assert set(result["analyzer_states"].values()) == {status}
    body["deep"]["status"] = "completed"
    assert calculate(body)["coverage"] == "partial"
    body = example()
    body["rules"]["findings"] = []
    assert calculate(body)["coverage"] == "complete"


def test_suspicious_auto_approval_and_permission_precedence():
    body = example()
    body["llm"]["risk"] = "suspicious"
    body["policy"] = {"auto_approve_risk": ["benign", "suspicious"], "require_human_review": [], "blocked_permissions": ["read_credentials"]}
    result = calculate(body)
    assert (result["final_risk"], result["admission_status"]) == ("suspicious", "APPROVED")
    body["declared_permissions"] = ["read_credentials"]
    result = calculate(body)
    assert (result["final_risk"], result["admission_status"]) == ("suspicious", "REJECTED")
    assert result["admission_reason"] == "blocked_permission"


def test_multi_source_aggregation_and_sandbox_trigger_precedes_classification():
    body = example()
    body["deep"]["findings"] = [{"kind": "network", "severity": "HIGH"}]
    body["sandbox"]["findings"] = [{"kind": "data_exfiltration", "severity": "HIGH"}]
    body["policy"] = {"risk_classification": {"network": "noise", "data_exfiltration": "blocking"}, "require_sandbox_for_risk": ["malicious"]}
    result = calculate(body)
    assert result["counts"] == {"blocking": 1, "risk": 1, "noise": 1}
    assert [item["source"] for item in result["findings"]] == ["rules", "deep", "sandbox"]
    assert result["interim_risk"] == "malicious"
    assert result["sandbox_required"] is True
    body["deep"]["findings"] = []
    result = calculate(body)
    assert result["interim_risk"] == "suspicious"
    assert result["sandbox_required"] is False
    assert result["final_risk"] == "malicious"


@pytest.fixture
def client(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Read-only simulation must not initialize a manager, persist policy, or run detection")

    monkeypatch.setattr(api_router, "AgentManager", unexpected)
    monkeypatch.setattr(CompanyPolicy, "save", unexpected)
    monkeypatch.setattr("agent_manager.core.vetting.VettingPipeline.vet", unexpected)
    monkeypatch.setattr("agent_manager.core.vetting.analyze_skill_with_llm_single_round", unexpected)
    app = FastAPI()
    app.include_router(api_router.router, prefix="/api/v1")
    with TestClient(app) as test_client:
        yield test_client


def test_api_calculates_draft_without_saving_or_running_detection(client):
    body = example()
    before = deepcopy(body)
    response = client.post("/api/v1/policy/simulate", json=body)
    assert response.status_code == 200
    assert response.json()["simulation"] is True
    assert response.json()["final_risk"] == "benign"
    assert body == before


@pytest.mark.parametrize("invalid", [
    {"rules": {"status": "completed", "findings": [{"kind": "invented", "severity": "HIGH"}]}},
    {"rules": {"status": "completed", "findings": [{"kind": "network", "severity": "invented"}]}},
    {"rules": {"status": "completed", "findings": [{"kind": "network", "severity": "HIGH"}] * 11}},
    {"policy": {"judgement_mode": "invented"}},
    {"llm": {"status": "completed"}},
    {"llm": {"status": "invented"}},
    {"policy": {"remote_api_key": "unexpected-field"}},
])
def test_api_rejects_invalid_inputs_with_stable_error(client, invalid):
    response = client.post("/api/v1/policy/simulate", json={**example(), **invalid})
    assert response.status_code == 422
    assert response.json()["error_code"] == "policy.simulation_invalid"
