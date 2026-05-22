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
      "SessionStart":  [{"matcher": "", "hooks": [{"type": "command", "command": "python3 -m agent_manager.hooks.agent_hook"}]}],
      "ConfigChange":  [{"matcher": "skills", "hooks": [{"type": "command", "command": "python3 -m agent_manager.hooks.agent_hook"}]}],
      "PreToolUse":    [{"matcher": "", "hooks": [{"type": "command", "command": "python3 -m agent_manager.hooks.agent_hook"}]}]
    }
  }
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Try to load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Session state directory - store state per session_id
SESSION_STATE_DIR = Path("/Users/nancy_yu/riversecurity/agent-manager/.claude/session-state")


# --------------------------------------------------------------------------- #
# Session state management (using session_id from event)                     #
# --------------------------------------------------------------------------- #

def _get_session_state_path(session_id: str) -> Path:
    """Get the path to the session state file for a given session_id."""
    SESSION_STATE_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_STATE_DIR / f"session-{session_id}.json"


def _load_session_state(session_id: str) -> dict:
    """Load session state from disk, returns empty dict if not found."""
    state_path = _get_session_state_path(session_id)
    if state_path.exists():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
                _log(f"Loaded session state for {session_id}: {state}")
                return state
        except Exception as e:
            _log(f"Error loading session state: {e}")
    return {}


def _save_session_state(session_id: str, state: dict) -> None:
    """Save session state to disk."""
    state_path = _get_session_state_path(session_id)
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f)
        _log(f"Saved session state for {session_id}: {state}")
    except Exception as e:
        _log(f"Error saving session state: {e}")


def _get_active_skills_from_state(session_id: str) -> list[str]:
    """Get active skills from session state."""
    state = _load_session_state(session_id)
    return state.get("active_skills", [])


def _set_active_skills_in_state(session_id: str, skills: list[str]) -> None:
    """Set active skills in session state."""
    state = _load_session_state(session_id)
    state["active_skills"] = skills
    _save_session_state(session_id, state)


# --------------------------------------------------------------------------- #
# Registry access                                                               #
# --------------------------------------------------------------------------- #

def _log(_msg: str) -> None:
    """No-op for backward compatibility."""
    pass


def _get_registry():
    from agent_manager.core.registry import Registry
    return Registry()


def _make_actor(session_id: str | None) -> str:
    """Create actor string from session_id."""
    if session_id:
        return f"Claude code {session_id}"
    return "Claude code"


def _emit_audit_event(event_type: str, entry=None, skill_name: str | None = None,
                      session_id: str | None = None, details: dict | None = None):
    """Emit an audit event to audit.jsonl."""
    from agent_manager.core.registry import make_event, AuditEvent
    import uuid
    registry = _get_registry()
    actor = _make_actor(session_id)

    if entry:
        registry.log_event(make_event(
            event_type, entry, actor=actor, details=details or {}
        ))
    else:
        # Create event without entry (for unknown skills)
        from datetime import datetime, timezone
        ev = AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            skill_id="unknown",
            skill_name=skill_name or "unknown",
            actor=actor,
            details=details or {},
        )
        registry.log_event(ev)


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
      1. AGENT_MANAGER_SKILLS_DIR env var (company-controlled directory)
      2. .claude/skills/ in the cwd
      3. ~/.claude/skills/
    """
    session_id = event.get("session_id", "")
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
            _log(f"Checked skill {name} (at {skill_md.parent}): {entry}")
            if entry is None or not entry.is_loadable():
                unregistered.append(f"{name} (at {skill_md.parent})")
                if entry is None:
                    _emit_audit_event(
                        "skill_load_blocked",
                        skill_name=name,
                        session_id=session_id,
                        details={"reason": "Skill not in registry"}
                    )
                else:
                    _emit_audit_event(
                        "skill_load_blocked",
                        entry=entry,
                        session_id=session_id,
                        details={"reason": f"Skill has status {entry.status.value}, not loadable"}
                    )
            else:
                active_names.append(name)
                _emit_audit_event(
                    "skill_load_allowed",
                    entry=entry,
                    session_id=session_id,
                    details={"status": entry.status.value}
                )

    _log(f"Active skills: {active_names}")
    # Persist active skills list for later hooks
    if session_id:
        _set_active_skills_in_state(session_id, active_names)

    if unregistered:
        _block(
            f"[agent-manager] Session blocked: {len(unregistered)} unregistered skill(s) found.\n"
            + "\n".join(f"  - {s}" for s in unregistered)
            + "\nRun: agent-manager submit <path> to register each skill."
        )


# --------------------------------------------------------------------------- #
# ConfigChange handler                                                          #
# --------------------------------------------------------------------------- #

def handle_config_change(event: dict) -> None:
    """
    Fires when a skill file is loaded mid-session (source == "skills").
    Verifies the incoming skill is registered before Claude processes its instructions.
    Updates the active-skills in session state.
    """
    session_id = event.get("session_id", "")
    file_path = event.get("file_path", "")
    skill_md = Path(file_path)

    if not skill_md.name == "SKILL.md":
        return  # Not a skill file

    name = _extract_name(skill_md)
    if name is None:
        _block(f"[agent-manager] Skill file {file_path!r} has no parseable name field.")

    registry = _get_registry()
    entry = registry.get_by_name(name)

    if entry is None:
        _emit_audit_event(
            "skill_load_blocked",
            skill_name=name,
            session_id=session_id,
            details={"reason": "Skill not in registry"}
        )
        _block(
            f"[agent-manager] Skill {name!r} is not in the registry.\n"
            f"Run: agent-manager submit {skill_md.parent} to register it."
        )

    if not entry.is_loadable():
        _emit_audit_event(
            "skill_load_blocked",
            entry=entry,
            session_id=session_id,
            details={"reason": f"Skill has status {entry.status.value}, not loadable"}
        )
        _block(
            f"[agent-manager] Skill {name!r} has status {entry.status.value} and cannot be loaded.\n"
            f"Status must be APPROVED or DEPLOYED."
        )

    # Verify signature if path is known
    if entry.signature and skill_md.parent.exists():
        from agent_manager.core.signer import verify_signature
        if not verify_signature(skill_md.parent, entry.signature):
            _emit_audit_event(
                "skill_tamper_detected",
                entry=entry,
                session_id=session_id,
                details={"reason": "Signature mismatch"}
            )
            _block(
                f"[agent-manager] Skill {name!r} FAILED signature verification.\n"
                f"The skill files may have been tampered with since approval."
            )

    # Add to active skills list
    if session_id:
        current = _get_active_skills_from_state(session_id)
        _log(f"config Active skills: {current}")
        if name not in current:
            current.append(name)
            _set_active_skills_in_state(session_id, current)
            _emit_audit_event(
                "skill_load_allowed",
                entry=entry,
                session_id=session_id,
                details={"status": entry.status.value}
            )


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
    session_id = event.get("session_id", "")
    tool_name = event.get("tool_name", "")
    active = _get_active_skills_from_state(session_id) if session_id else []
    _log(f"Active skills: {active}")

    if not active:
        return  # No active skills → no restrictions

    registry = _get_registry()
    all_allowed: set[str] = set(["Skill"])
    any_has_declarations = False

    for skill_name in active:
        entry = registry.get_by_name(skill_name)
        if entry is None:
            # Skill was active but is no longer in registry (e.g., retired mid-session)
            _emit_audit_event(
                "tool_blocked",
                skill_name=skill_name,
                session_id=session_id,
                details={"tool": tool_name, "reason": "Skill no longer in registry"}
            )
            _block(
                f"[agent-manager] Active skill {skill_name!r} is no longer in the registry.\n"
                f"Possible retirement during session. Restart the agent to continue."
            )

        if not entry.is_loadable():
            _emit_audit_event(
                "tool_blocked",
                entry=entry,
                session_id=session_id,
                details={"tool": tool_name, "reason": f"Skill not loadable (status: {entry.status.value})"}
            )
            _block(
                f"[agent-manager] Active skill {skill_name!r} is no longer loadable "
                f"(status: {entry.status.value}). Possible retirement mid-session."
            )

        if entry.allowed_tools:
            any_has_declarations = True
            all_allowed.update(entry.allowed_tools)

    _log(f"Allowed tools: {all_allowed}")

    if not any_has_declarations:
        # Emit tool_invoked for all active skills with no restrictions
        for skill_name in active:
            entry = registry.get_by_name(skill_name)
            if entry:
                _emit_audit_event(
                    "tool_invoked",
                    entry=entry,
                    session_id=session_id,
                    details={"tool": tool_name, "allowed": True}
                )
        return  # All active skills have no restrictions

    if tool_name not in all_allowed:
        # Emit tool_blocked for all active skills
        for skill_name in active:
            entry = registry.get_by_name(skill_name)
            if entry:
                _emit_audit_event(
                    "tool_blocked",
                    entry=entry,
                    session_id=session_id,
                    details={"tool": tool_name, "reason": "Tool not in allowed_tools"}
                )
        active_list = ", ".join(f"{s!r}" for s in active)
        allowed_list = ", ".join(sorted(all_allowed))
        _block(
            f"[agent-manager] Tool {tool_name!r} is not permitted by active skill(s): {active_list}.\n"
            f"Allowed tools: {allowed_list}"
        )

    # Emit tool_invoked for all active skills that allow this tool
    for skill_name in active:
        entry = registry.get_by_name(skill_name)
        if entry:
            _emit_audit_event(
                "tool_invoked",
                entry=entry,
                session_id=session_id,
                details={"tool": tool_name, "allowed": True}
            )


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _candidate_skill_dirs(cwd: str) -> list[Path]:
    """Return skill directories to scan, in priority order."""
    dirs: list[Path] = []

    # 1. Company-controlled directory (highest priority)
    company_dir = os.environ.get("AGENT_MANAGER_SKILLS_DIR")
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
    except Exception as e:
        _log(f"Error extracting name from {skill_md}: {e}")
    return None


# --------------------------------------------------------------------------- #
# Public API for programmatic access (used by backend API)                   #
# --------------------------------------------------------------------------- #

def process_event(event: dict) -> tuple[bool, str]:
    """
    Process a hook event programmatically.

    Returns: (allowed: bool, message: str)
    """
    import io
    import contextlib

    hook_event = event.get("hook_event_name", "")

    # Capture stderr
    stderr_capture = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr_capture):
            if hook_event == "SessionStart":
                handle_session_start(event)
            elif hook_event == "ConfigChange" and event.get("source") == "skills":
                handle_config_change(event)
            elif hook_event == "PreToolUse":
                handle_pre_tool_use(event)
        return True, ""
    except SystemExit:
        message = stderr_capture.getvalue().strip()
        return False, message
    except Exception as e:
        # Hook errors must not block the agent — log and continue
        message = f"[agent-manager hook error] {e}"
        print(message, file=sys.stderr)
        return True, message


# --------------------------------------------------------------------------- #
# Main dispatch                                                                 #
# --------------------------------------------------------------------------- #

def main() -> None:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)  # Malformed input → allow (don't block on hook errors)

    allowed, message = process_event(event)
    if not allowed:
        print(message, file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
