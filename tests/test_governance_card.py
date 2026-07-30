"""Tests for governance skill card artifacts and API."""

from __future__ import annotations

import textwrap

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_manager.api import router as api_router
from agent_manager.core.governance_card import generate_governance_card, governance_card_path
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import SkillOrigin, SourceInfo
from agent_manager.core.policy import CompanyPolicy


def _skill_dir(tmp_path):
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: card-skill
        description: Generates useful reports
        license: MIT
        allowed-tools: Read
        ---

        # Card Skill
    """), encoding="utf-8")
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "run.py").write_text("print('ok')\n", encoding="utf-8")
    return skill_dir


def test_generate_governance_card_contains_core_sections(tmp_path):
    mgr = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    entry = mgr.submit(_skill_dir(tmp_path), SourceInfo(origin=SkillOrigin.LOCAL))
    card = generate_governance_card(entry, mgr.registry)

    assert "# Governance Card（治理卡片）：card-skill" in card
    assert "## 基础信息" in card
    assert "## 内容身份" in card
    assert "## 检测摘要" in card
    assert "## 人工审核" in card
    assert "## 审计记录" in card
    assert "- 状态：`APPROVED（已批准）`" in card
    assert "- 风险等级：`benign（安全）`" in card
    assert "## 判断依据" in card
    assert entry.content_fingerprint in card
    assert entry.scan_cache_key in card


def test_manager_generates_governance_card_after_vetting(tmp_path):
    mgr = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    entry = mgr.submit(_skill_dir(tmp_path), SourceInfo(origin=SkillOrigin.LOCAL))

    path = governance_card_path(mgr.registry.data_dir, entry.skill_id)

    assert path.exists()
    assert "Governance Card（治理卡片）" in path.read_text(encoding="utf-8")
    refreshed = mgr.refresh_governance_card(entry.skill_id)
    assert refreshed["skill_id"] == entry.skill_id
    assert refreshed["content"] == path.read_text(encoding="utf-8")


def test_manager_regenerates_legacy_english_governance_card(tmp_path):
    mgr = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    entry = mgr.submit(_skill_dir(tmp_path), SourceInfo(origin=SkillOrigin.LOCAL))
    path = governance_card_path(mgr.registry.data_dir, entry.skill_id)
    path.write_text("# Governance Skill Card: card-skill\n\nGenerated at: old\n", encoding="utf-8")

    card = mgr.get_governance_card(entry.skill_id)

    assert "# Governance Card（治理卡片）：card-skill" in card["content"]
    assert "Governance Skill Card" not in path.read_text(encoding="utf-8")


def test_governance_card_api_get_and_refresh(tmp_path):
    mgr = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    entry = mgr.submit(_skill_dir(tmp_path), SourceInfo(origin=SkillOrigin.LOCAL))

    app = FastAPI()
    app.include_router(api_router.router, prefix="/api/v1")
    app.dependency_overrides[api_router.get_manager] = lambda: mgr
    client = TestClient(app)

    get_response = client.get(f"/api/v1/skills/{entry.skill_id}/governance-card")
    assert get_response.status_code == 200
    assert get_response.json()["skill_id"] == entry.skill_id
    assert "Governance Card（治理卡片）" in get_response.json()["content"]

    refresh_response = client.post(f"/api/v1/skills/{entry.skill_id}/governance-card/refresh")
    assert refresh_response.status_code == 200
    assert refresh_response.json()["skill_id"] == entry.skill_id
    assert "generated_at" in refresh_response.json()
