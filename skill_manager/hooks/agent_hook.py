"""
Claude Code hook — enforces skill registry at runtime.

Receives JSON events from Claude Code on stdin.
Communicates decisions via exit code and stderr.

Hook events handled:
  SessionStart   — scan all skills in the session's skill dirs; block if any unregistered
  ConfigChange   — verify a newly-loaded skill is registered; update the active-skill env
  PreToolUse     — enforce allowed_tools for all currently active skills

Exit codes:
  0  — allow (or not applicable)
  2  — block; stderr message is fed back to Claude as the reason

Usage (in .claude/settings.json):
  {
    "hooks": {
      "SessionStart":  [{"matcher": "", "hooks": [{"type": "command", "command": "python3 -m skill_manager.hooks.agent_hook"}]}],
      "ConfigChange":  [{"matcher": "skills", "hooks": [{"type": "command", "command": "python3 -m skill_manager.hooks.agent_hook"}]}],
      "PreToolUse":    [{"matcher": "", "hooks": [{"type": "command", "command": "python3 -m skill_manager.hooks.agent_hook"}]}]
    }
  }
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


# --------------------------------------------------------------------------- #
# Registry access                                                               #
# --------------------------------------------------------------------------- #

def _get_registry():
    from skill_manager.core.registry import Registry
    return Registry()


def _active_skills() -> list[str]:
    """Return skill names stored in SKILL_MANAGER_ACTIVE_SKILLS env var."""
    raw = os.environ.get("SKILL_MANAGER_ACTIVE_SKILLS", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def _write_env(key: str, value: str) -> None:
    """Persist an environment variable for the rest of the Claude Code session."""
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        with open(env_file, "a") as f:
            f.write(f"export {key}={json.dumps(value)}\n")


def _block(reason: str) -> None:
    print(reason, file=sys.stderr)
    sys.exit(2)


# --------------------------------------------------------------------------- #
# SessionStart handler                                                          #
# --------------------------------------------------------------------------- #

def handle_session_start(event: dict) -> None:
    """
    At session start, find all skill files visible to the agent and verify
    each one is in the registry.  If any skill is unregistered, block the
    session from proceeding.

    Skill directories searched (in order):
      1. SKILL_MANAGER_SKILLS_DIR env var (company-controlled directory)
      2. .claude/skills/ in the cwd
      3. ~/.claude/skills/
    """
    cwd = event.get("cwd", ".")
    skill_dirs = _candidate_skill_dirs(cwd)

    registry = _get_registry()
    unregistered: list[str] = []
    active_names: list[str] = []

    for skill_dir in skill_dirs:
        for skill_md in sorted(skill_dir.glob("*/SKILL.md")):
            name = _extract_name(skill_md)
            if name is None:
                continue
            entry = registry.get_by_name(name)
            if entry is None or not entry.is_loadable():
                unregistered.append(f"{name} (at {skill_md.parent})")
            else:
                active_names.append(name)

    if unregistered:
        _block(
            f"[skill-manager] Session blocked: {len(unregistered)} unregistered skill(s) found.\n"
            + "\n".join(f"  - {s}" for s in unregistered)
            + "\nRun: skill-manager submit <path> to register each skill."
        )

    # Persist active skills list for PreToolUse hooks later in the session
    if active_names:
        _write_env("SKILL_MANAGER_ACTIVE_SKILLS", ",".join(active_names))


# --------------------------------------------------------------------------- #
# ConfigChange handler                                                          #
# --------------------------------------------------------------------------- #

def handle_config_change(event: dict) -> None:
    """
    Fires when a skill file is loaded mid-session (source == "skills").
    Verifies the incoming skill is registered before Claude processes its instructions.
    Updates the active-skills env var.
    """
    file_path = event.get("file_path", "")
    skill_md = Path(file_path)

    if not skill_md.name == "SKILL.md":
        return  # Not a skill file

    name = _extract_name(skill_md)
    if name is None:
        _block(f"[skill-manager] Skill file {file_path!r} has no parseable name field.")

    registry = _get_registry()
    entry = registry.get_by_name(name)

    if entry is None:
        _block(
            f"[skill-manager] Skill {name!r} is not in the registry.\n"
            f"Run: skill-manager submit {skill_md.parent} to register it."
        )

    if not entry.is_loadable():
        _block(
            f"[skill-manager] Skill {name!r} has status {entry.status.value} and cannot be loaded.\n"
            f"Status must be APPROVED or DEPLOYED."
        )

    # Verify signature if path is known
    if entry.signature and skill_md.parent.exists():
        from skill_manager.core.signer import verify_signature
        if not verify_signature(skill_md.parent, entry.signature):
            _block(
                f"[skill-manager] Skill {name!r} FAILED signature verification.\n"
                f"The skill files may have been tampered with since approval."
            )

    # Add to active skills list
    current = _active_skills()
    if name not in current:
        current.append(name)
        _write_env("SKILL_MANAGER_ACTIVE_SKILLS", ",".join(current))


# --------------------------------------------------------------------------- #
# PreToolUse handler                                                            #
# --------------------------------------------------------------------------- #

def handle_pre_tool_use(event: dict) -> None:
    """
    Before every tool call, enforce the allowed_tools of all active skills.

    Policy:
    - If no skills are active → allow all tools (no skill context)
    - If skills are active and ALL have empty allowed_tools → allow all tools
    - If ANY active skill declares allowed_tools, compute the UNION of permissions
      from all active skills and enforce it
    """
    tool_name = event.get("tool_name", "")
    active = _active_skills()

    if not active:
        return  # No active skills → no restrictions

    registry = _get_registry()
    all_allowed: set[str] = set()
    any_has_declarations = False

    for skill_name in active:
        entry = registry.get_by_name(skill_name)
        if entry is None:
            # Skill was active but is no longer in registry (e.g., retired mid-session)
            _block(
                f"[skill-manager] Active skill {skill_name!r} is no longer in the registry.\n"
                f"Possible retirement during session. Restart the agent to continue."
            )

        if not entry.is_loadable():
            _block(
                f"[skill-manager] Active skill {skill_name!r} is no longer loadable "
                f"(status: {entry.status.value}). Possible retirement mid-session."
            )

        if entry.allowed_tools:
            any_has_declarations = True
            all_allowed.update(entry.allowed_tools)

    if not any_has_declarations:
        return  # All active skills have no restrictions

    if tool_name not in all_allowed:
        active_list = ", ".join(f"{s!r}" for s in active)
        allowed_list = ", ".join(sorted(all_allowed))
        _block(
            f"[skill-manager] Tool {tool_name!r} is not permitted by active skill(s): {active_list}.\n"
            f"Allowed tools: {allowed_list}"
        )


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _candidate_skill_dirs(cwd: str) -> list[Path]:
    """Return skill directories to scan, in priority order."""
    dirs: list[Path] = []

    # 1. Company-controlled directory (highest priority)
    company_dir = os.environ.get("SKILL_MANAGER_SKILLS_DIR")
    if company_dir:
        p = Path(company_dir)
        if p.is_dir():
            dirs.append(p)

    # 2. Project .claude/skills/
    project_skills = Path(cwd) / ".claude" / "skills"
    if project_skills.is_dir():
        dirs.append(project_skills)

    # 3. Global ~/.claude/skills/
    global_skills = Path.home() / ".claude" / "skills"
    if global_skills.is_dir():
        dirs.append(global_skills)

    return dirs


def _extract_name(skill_md: Path) -> str | None:
    """Read the 'name' field from a SKILL.md frontmatter."""
    try:
        content = skill_md.read_text(encoding="utf-8")
        in_fm = False
        for i, line in enumerate(content.splitlines()):
            if i == 0 and line.strip() == "---":
                in_fm = True
                continue
            if in_fm:
                if line.strip() == "---":
                    break
                if line.startswith("name:"):
                    return line.split(":", 1)[1].strip().strip("\"'")
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- #
# Main dispatch                                                                 #
# --------------------------------------------------------------------------- #

def main() -> None:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)  # Malformed input → allow (don't block on hook errors)

    hook_event = event.get("hook_event_name", "")

    try:
        if hook_event == "SessionStart":
            handle_session_start(event)
        elif hook_event == "ConfigChange" and event.get("source") == "skills":
            handle_config_change(event)
        elif hook_event == "PreToolUse":
            handle_pre_tool_use(event)
    except SystemExit:
        raise
    except Exception as e:
        # Hook errors must not block the agent — log and continue
        print(f"[skill-manager hook error] {e}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
