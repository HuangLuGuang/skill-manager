import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "demo" / "codex-agent-manager-hook" / "codex_agent_guard_hook.py"
SPEC = importlib.util.spec_from_file_location("codex_agent_guard_hook", SCRIPT)
hook = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(hook)


def test_pre_tool_use_blocks_when_any_discovered_skill_fails(tmp_path, monkeypatch):
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "unsafe-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: unsafe-skill\n---\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_MANAGER_CODEX_SKILLS_DIRS", str(skill_root))
    monkeypatch.setattr(hook, "verify_skill", lambda *_args: (_ for _ in ()).throw(hook.GuardError("未批准")))

    try:
        hook.evaluate({"hook_event_name": "PreToolUse", "cwd": str(tmp_path), "turn_id": "turn-1"})
    except hook.GuardError as exc:
        assert str(exc) == "未批准"
    else:
        raise AssertionError("PreToolUse should fail closed")


def test_deny_uses_codex_pre_tool_use_schema(capsys):
    hook.deny("未批准")

    payload = json.loads(capsys.readouterr().out)
    output = payload["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    assert output["permissionDecision"] == "deny"
    assert "未批准" in output["permissionDecisionReason"]


def test_configured_skill_roots_do_not_replace_repository_roots(tmp_path, monkeypatch):
    configured = tmp_path / "configured"
    configured.mkdir()
    repository = tmp_path / "repository"
    repository_skills = repository / ".agents" / "skills"
    repository_skills.mkdir(parents=True)
    (repository / ".git").mkdir()
    monkeypatch.setenv("AGENT_MANAGER_CODEX_SKILLS_DIRS", str(configured))

    roots = hook.skill_roots(repository)

    assert configured.resolve() in roots
    assert repository_skills.resolve() in roots
