from click.testing import CliRunner

from agent_manager.cli import cli
from agent_manager.core.models import (
    RegistryEntry,
    SkillOrigin,
    SkillStatus,
    SourceInfo,
)


def _entry(name: str, tools: list[str]) -> RegistryEntry:
    return RegistryEntry(
        skill_id=f"id-{name}",
        name=name,
        description="test",
        source=SourceInfo(origin=SkillOrigin.LOCAL),
        status=SkillStatus.APPROVED,
        allowed_tools=tools,
    )


def test_audit_tool_permissions_reports_loadable_empty_declarations(monkeypatch):
    class Manager:
        def list_skills(self):
            return [
                _entry("missing-tools", []),
                _entry("declared-tools", ["Read"]),
            ]

    monkeypatch.setattr(cli, "_load_manager", lambda _policy: Manager())

    result = CliRunner().invoke(
        cli.main,
        ["registry", "audit-tool-permissions", "--json"],
    )

    assert result.exit_code == 2
    assert '"name": "missing-tools"' in result.output
    assert "declared-tools" not in result.output


def test_audit_tool_permissions_passes_when_no_findings(monkeypatch):
    class Manager:
        def list_skills(self):
            return [_entry("declared-tools", ["Read"])]

    monkeypatch.setattr(cli, "_load_manager", lambda _policy: Manager())

    result = CliRunner().invoke(
        cli.main,
        ["registry", "audit-tool-permissions", "--json"],
    )

    assert result.exit_code == 0
    assert result.output.strip() == "[]"


def test_signing_key_init_is_explicit_and_idempotent(tmp_path, monkeypatch):
    key_path = tmp_path / "signing" / "server.pem"
    monkeypatch.setenv("AGENT_MANAGER_SIGNING_PRIVATE_KEY_PATH", str(key_path))

    first = CliRunner().invoke(cli.main, ["signing-key", "init"])
    original = key_path.read_bytes()
    second = CliRunner().invoke(cli.main, ["signing-key", "init"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert key_path.read_bytes() == original
    assert key_path.stat().st_mode & 0o777 == 0o600
