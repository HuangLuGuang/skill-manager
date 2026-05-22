"""
Install the agent-manager hooks into a Claude Code project.

Writes hook configuration into .claude/settings.json (project scope)
or ~/.claude/settings.json (global scope, affects all projects).

Usage:
  python -m agent_manager.hooks.install              # project scope
  python -m agent_manager.hooks.install --global     # global scope
  python -m agent_manager.hooks.install --strict     # also enforce SessionStart
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click


HOOK_COMMAND = "python3 -m agent_manager.hooks.agent_hook"

_BASE_HOOKS = {
    "ConfigChange": [
        {
            "matcher": "skills",
            "hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": 10}],
        }
    ],
    "PreToolUse": [
        {
            "matcher": "",
            "hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": 10}],
        }
    ],
}

_STRICT_HOOKS = {
    **_BASE_HOOKS,
    "SessionStart": [
        {
            "matcher": "",
            "hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": 30}],
        }
    ],
}


@click.command()
@click.option("--global", "global_scope", is_flag=True, default=False,
              help="Install into ~/.claude/settings.json (all projects)")
@click.option("--strict", is_flag=True, default=False,
              help="Also add SessionStart hook to verify all skills at startup")
@click.option("--dry-run", is_flag=True, default=False,
              help="Print what would be written without modifying files")
def main(global_scope: bool, strict: bool, dry_run: bool):
    """Install agent-manager hooks into Claude Code settings."""
    if global_scope:
        settings_path = Path.home() / ".claude" / "settings.json"
    else:
        settings_path = Path(".claude") / "settings.json"

    # Load existing settings
    if settings_path.exists():
        existing = json.loads(settings_path.read_text())
    else:
        existing = {}

    hooks_to_add = _STRICT_HOOKS if strict else _BASE_HOOKS

    # Merge: add our hooks without clobbering existing ones
    existing_hooks = existing.setdefault("hooks", {})
    for event, configs in hooks_to_add.items():
        event_list = existing_hooks.setdefault(event, [])
        for config in configs:
            # Avoid duplicates
            if not any(
                h.get("hooks", [{}])[0].get("command") == HOOK_COMMAND
                for h in event_list
            ):
                event_list.append(config)

    result = json.dumps(existing, indent=2)

    if dry_run:
        click.echo(f"[dry-run] Would write to {settings_path}:")
        click.echo(result)
        return

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(result)
    click.echo(f"Installed agent-manager hooks in {settings_path}")

    if strict:
        click.echo("  SessionStart: verify all skills in skills directory at startup")
    click.echo("  ConfigChange (skills): verify each skill as it is loaded")
    click.echo("  PreToolUse: enforce allowed_tools for active skills")
    click.echo()
    click.echo("Next steps:")
    click.echo("  export AGENT_MANAGER_SIGNING_KEY=$(openssl rand -hex 32)")
    click.echo("  agent-manager submit ./my-skill")


if __name__ == "__main__":
    main()
