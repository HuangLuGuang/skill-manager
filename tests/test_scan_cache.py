import textwrap

from agent_manager.core.manager import AgentManager
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.scan_cache import compute_scan_context_fingerprint


def _write_skill(path, name="cached-skill"):
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        description: Cache test skill
        license: MIT
        allowed-tools: Read
        ---

        # Cache test
    """), encoding="utf-8")


def test_reuses_scan_when_content_and_context_match(tmp_path):
    data_dir = tmp_path / "data"
    mgr = AgentManager(policy=CompanyPolicy.default(), data_dir=data_dir)
    skill_a = tmp_path / "skill-a"
    skill_b = tmp_path / "skill-b"
    _write_skill(skill_a)
    _write_skill(skill_b)

    first = mgr.submit(skill_a)
    second = mgr.submit(skill_b)

    assert first.scan_reused is False
    assert second.scan_reused is True
    assert second.reused_from_skill_id == first.skill_id
    assert second.content_fingerprint == first.content_fingerprint
    assert second.scan_context_fingerprint == first.scan_context_fingerprint
    assert second.scan_cache_key == first.scan_cache_key
    assert second.vetting.scan_report["scan_reused"] is True


def test_scan_context_change_prevents_reuse(tmp_path):
    data_dir = tmp_path / "data"
    mgr = AgentManager(policy=CompanyPolicy.default(), data_dir=data_dir)
    skill_a = tmp_path / "skill-a"
    skill_b = tmp_path / "skill-b"
    _write_skill(skill_a)
    _write_skill(skill_b)

    first = mgr.submit(skill_a, use_behavioral=False)
    second = mgr.submit(skill_b, use_behavioral=True)

    assert first.scan_reused is False
    assert second.scan_reused is False
    assert second.reused_from_skill_id is None
    assert second.content_fingerprint == first.content_fingerprint
    assert second.scan_context_fingerprint != first.scan_context_fingerprint
    assert second.scan_cache_key != first.scan_cache_key


def test_deep_scan_option_change_prevents_reuse(tmp_path):
    data_dir = tmp_path / "data"
    mgr = AgentManager(policy=CompanyPolicy.default(), data_dir=data_dir)
    skill_a = tmp_path / "skill-a"
    skill_b = tmp_path / "skill-b"
    _write_skill(skill_a)
    _write_skill(skill_b)

    first = mgr.submit(skill_a, use_skillspector=False)
    second = mgr.submit(skill_b, use_skillspector=True)

    assert first.scan_reused is False
    assert second.scan_reused is False
    assert second.content_fingerprint == first.content_fingerprint
    assert second.scan_context_fingerprint != first.scan_context_fingerprint


def test_legacy_skillspector_llm_setting_does_not_split_static_scan_cache():
    common = {
        "use_behavioral": False,
        "use_llm": False,
        "use_sandbox": False,
        "use_skillspector": True,
    }

    disabled = compute_scan_context_fingerprint(
        CompanyPolicy({"skillspector_use_llm": False}),
        **common,
    )
    legacy_enabled = compute_scan_context_fingerprint(
        CompanyPolicy({"skillspector_use_llm": True}),
        **common,
    )

    assert disabled == legacy_enabled


def test_registry_completed_match_rebuilds_missing_cache_index(tmp_path):
    data_dir = tmp_path / "data"
    mgr = AgentManager(policy=CompanyPolicy.default(), data_dir=data_dir)
    skill_a = tmp_path / "skill-a"
    skill_b = tmp_path / "skill-b"
    _write_skill(skill_a)
    _write_skill(skill_b)

    first = mgr.submit(skill_a)
    cache_index = data_dir / "scan_cache" / "index.json"
    cache_index.unlink()

    second = mgr.submit(skill_b)

    assert first.scan_reused is False
    assert second.scan_reused is True
    assert second.reused_from_skill_id == first.skill_id
    assert cache_index.exists()
