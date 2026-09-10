from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_manager.api import router as api_router
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import RiskLevel, SkillStatus, VettingResult
from agent_manager.core.policy import CompanyPolicy


def test_suspicious_approval_persists_through_api_and_signs_submitted_skill(tmp_path, monkeypatch):
    policy_path = tmp_path / "policy.yaml"
    monkeypatch.setattr(api_router, "_manager", None)
    monkeypatch.setattr(api_router, "_policy_path_for_write", lambda: policy_path)
    monkeypatch.setattr(api_router, "AgentManager", lambda **kwargs: AgentManager(data_dir=tmp_path / "data", **kwargs))
    app = FastAPI()
    app.include_router(api_router.router, prefix="/api/v1")
    payload = CompanyPolicy.default().to_dict()
    payload.update(auto_approve_risk=["benign", "suspicious"], require_human_review=[])

    with TestClient(app) as client:
        response = client.put("/api/v1/policy", json=payload)
        assert response.status_code == 200
        saved = client.get("/api/v1/policy")
        assert saved.status_code == 200
        assert saved.json()["policy"]["auto_approve_risk"] == ["benign", "suspicious"]

    policy = CompanyPolicy.load(policy_path)
    assert policy.decide(RiskLevel.SUSPICIOUS, []) == SkillStatus.APPROVED
    manager = AgentManager(policy=policy, data_dir=tmp_path / "reloaded")
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: approval-example\ndescription: Policy integration test\n---\n", encoding="utf-8")
    monkeypatch.setattr(manager.vetting, "vet", lambda *args, **kwargs: (
        VettingResult(risk_level=RiskLevel.SUSPICIOUS, findings_count=1,
                      scan_report={"findings": [{"severity": "MEDIUM", "rule": "network_access"}]}),
        [], "approval-example", "Policy integration test", [],
    ))
    entry = manager.submit(skill)
    assert entry.risk_level == RiskLevel.SUSPICIOUS
    assert entry.status == SkillStatus.APPROVED
    assert entry.signature
    assert entry.approved_by == "auto-policy"
    assert manager.list_review_queue() == []


def test_existing_policy_payload_retains_default_admission_actions():
    payload = CompanyPolicy.default().to_dict()
    payload.pop("auto_approve_risk")
    restored = CompanyPolicy(api_router.PolicyPayload(**payload).model_dump())
    assert restored.decide(RiskLevel.SUSPICIOUS, []) == SkillStatus.VETTED
