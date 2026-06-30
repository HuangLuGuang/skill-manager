#!/usr/bin/env python3
"""
Claude Code Agent Guard Hook - PreToolUse Only

Receives JSON events from Claude Code on stdin.
For PreToolUse events, verify active skills using verify functionality.

Hook events handled:
  PreToolUse     - verify active skills using verify-skill-signature and can-load APIs

Exit codes:
  0  - allow (or not applicable)
  2  - block; stderr message is fed back to Claude as the reason
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import urllib.parse
from pathlib import Path
from typing import Any

import httpx

# Try to load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Session state directory
_DEFAULT_BASE_DIR = Path.home() / ".agent-manager"
_DEFAULT_SESSION_STATE_DIR = _DEFAULT_BASE_DIR / "session-state"
_DEFAULT_LOG_FILE = _DEFAULT_BASE_DIR / "logs" / "agent_guard_hook.log"

# Default ignores for signature calculation
DEFAULT_IGNORES = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}
SIGNING_KEY_ENV = "AGENT_MANAGER_SIGNING_KEY"
_ENV_LOADED = False


def _log(msg: str) -> None:
    """Log hook diagnostic messages to a local file."""
    try:
        from datetime import datetime, timezone
        log_file = Path(os.environ.get("AGENT_MANAGER_HOOK_LOG_FILE", _DEFAULT_LOG_FILE))
        log_file.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {msg}\n")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Session state management                                                    #
# --------------------------------------------------------------------------- #

def _get_session_state_path(session_id: str) -> Path:
    """Get the path to the session state file for a given session_id."""
    session_state_dir = Path(os.environ.get("AGENT_MANAGER_SESSION_STATE_DIR", _DEFAULT_SESSION_STATE_DIR))
    session_state_dir.mkdir(parents=True, exist_ok=True)
    return session_state_dir / f"session-{session_id}.json"


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
# Verify functions from agent_manager_skill_guard.py                          #
# --------------------------------------------------------------------------- #

def signing_key() -> str:
    global _ENV_LOADED
    if not _ENV_LOADED and not os.environ.get("ENV_LOADED"):
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        _ENV_LOADED = True
    return os.environ.get(SIGNING_KEY_ENV, "").strip()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_skill_files(skill_dir: str | Path, ignores: set[str] | None = None) -> list[Path]:
    root = Path(skill_dir).resolve()
    ignored = ignores or set()
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in ignored for part in rel_parts):
            continue
        files.append(path)
    return files


def compute_skill_signature(skill_dir: str | Path, ignores: set[str] | None = None) -> str:
    root = Path(skill_dir).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    parts = []
    files = iter_skill_files(root, ignores=ignores) if ignores is not None else sorted(item for item in root.rglob("*") if item.is_file())
    for path in files:
        rel = path.relative_to(root).as_posix()
        parts.append(f"{rel}:{file_sha256(path)}\n")

    content = "".join(parts).encode()
    key = signing_key()
    if key:
        return hmac.new(key.encode(), content, hashlib.sha256).hexdigest()
    return hashlib.sha256(content).hexdigest()


def read_skill_name(skill_dir: str | Path) -> str | None:
    skill_md = Path(skill_dir).resolve() / "SKILL.md"
    if not skill_md.is_file():
        return None
    try:
        with skill_md.open("r", encoding="utf-8", errors="replace") as handle:
            first = handle.readline().strip()
            if first != "---":
                return None
            for line in handle:
                text = line.strip()
                if text == "---":
                    return None
                if text.startswith("name:"):
                    return text.split(":", 1)[1].strip().strip("\"'")
    except OSError:
        return None
    return None


def normalize_base_url(value: str) -> str:
    return value.rstrip("/")


def resolve_server() -> str:
    server = os.environ.get("AGENT_MANAGER_BASE_URL")
    if not server:
        raise ValueError("Missing Agent Manager URL, please set AGENT_MANAGER_BASE_URL")
    return normalize_base_url(server)


def resolve_token() -> str:
    token = os.environ.get("AGENT_MANAGER_API_TOKEN")
    if not token:
        raise ValueError("Missing Agent Manager API token, please set AGENT_MANAGER_API_TOKEN")
    return token 


def resolve_agent_id(session_id: str | None = None) -> str:
    agent_id = (os.environ.get("AGENT_ID") or "").strip()
    if agent_id:
        return agent_id
    if session_id:
        return f"claude-code-{session_id}"
    return f"claude-code-{os.getpid()}"


# --------------------------------------------------------------------------- #
# API client - verify functionality only (with token)                        #
# --------------------------------------------------------------------------- #

def verify_skill_signature(
    client: httpx.Client,
    server: str,
    token: str,
    skill_dir: Path,
    skill_name: str | None = None,
    agent_id: str | None = None,
    ignores: set[str] | None = None,
) -> dict[str, Any]:
    """Verify skill signature via API (with token)."""
    signature = compute_skill_signature(skill_dir, ignores=ignores)
    _log(f"Skill signature: {signature} for {skill_dir}")

    body = {
        "local_signature": signature,
        "agent_id": agent_id or resolve_agent_id(),
    }
    if skill_name:
        body["skill_name"] = skill_name

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = client.post(
        f"{server}/api/v1/access/runtime/verify-skill-signature",
        json=body,
        headers=headers,
    )
    response.raise_for_status()
    result = response.json()
    _log(f"verify-skill-signature result: {result}")
    return result


def can_load_skill(
    client: httpx.Client,
    server: str,
    token: str,
    skill_name: str,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Check if skill can be loaded via API (with token)."""
    url = f"{server}/api/v1/access/runtime/can-load/{urllib.parse.quote(skill_name)}"
    if agent_id:
        url += f"?agent_id={urllib.parse.quote(agent_id)}"

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = client.get(
        url,
        headers=headers,
    )
    response.raise_for_status()
    result = response.json()
    _log(f"can-load result for {skill_name}: {result}")
    return result


def verify_skill(
    client: httpx.Client,
    server: str,
    token: str,
    skill_dir: Path,
    agent_id: str,
    skill_name: str | None = None,
) -> tuple[bool, str]:
    """
    Full skill verification: signature + can-load.
    Returns (allowed: bool, message: str)
    """
    if skill_name is None:
        skill_name = read_skill_name(skill_dir)
        if not skill_name:
            return False, f"Cannot identify skill name from {skill_dir}"

    try:
        # Step 1: Verify signature
        verify_result = verify_skill_signature(
            client, server, token, skill_dir, skill_name, agent_id, ignores=DEFAULT_IGNORES
        )
        if not verify_result.get("allowed"):
            reason = verify_result.get("reason") or "Content integrity verification failed"
            status = verify_result.get("status", "")
            return False, f"Skill {skill_name!r} blocked: {reason} (status: {status})"

        verified_name = verify_result.get("skill_name") or skill_name
        if not verified_name:
            return False, f"Skill {skill_name!r} blocked: platform did not return skill name"

        if verify_result.get("status") != "APPROVED":
            return False, f"Skill {verified_name!r} is not approved (status: {verify_result.get('status')})"

        # Step 2: Check can-load
        can_load_result = can_load_skill(client, server, token, verified_name, agent_id)
        if not can_load_result.get("allowed"):
            reason = can_load_result.get("reason") or "Status does not allow loading"
            status = can_load_result.get("status", "")
            return False, f"Skill {verified_name!r} blocked: {reason} (status: {status})"

        if can_load_result.get("status") != "APPROVED":
            return False, f"Skill {verified_name!r} is not approved (status: {can_load_result.get('status')})"

        return True, verified_name

    except httpx.HTTPError as e:
        _log(f"API error verifying skill {skill_name}: {e}")
        return False, f"API error verifying skill {skill_name!r}: {e}"


# --------------------------------------------------------------------------- #
# Skill directory scanning                                                    #
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


def _scan_skill_dirs(cwd: str) -> dict[str, Path]:
    """Scan skill directories and return map of skill name to skill dir."""
    skill_dir_map: dict[str, Path] = {}
    skill_dirs = _candidate_skill_dirs(cwd)
    for skill_dir in skill_dirs:
        for skill_md in sorted(skill_dir.glob("*/SKILL.md")):
            name = read_skill_name(skill_md.parent)
            if name:
                skill_dir_map[name] = skill_md.parent
    return skill_dir_map


# --------------------------------------------------------------------------- #
# SessionStart handler (to track active skills)                               #
# --------------------------------------------------------------------------- #

def handle_session_start(event: dict, client: httpx.Client, server: str, token: str) -> None:
    """
    At session start, scan skills and track which are active.
    """
    session_id = event.get("session_id", "")
    cwd = event.get("cwd", ".")
    agent_id = resolve_agent_id(session_id)

    skill_dirs = _candidate_skill_dirs(cwd)
    skill_dir_map = _scan_skill_dirs(cwd)
    active_names: list[str] = []

    # Try to verify all skills initially, but only track those that pass
    for skill_name, skill_dir in skill_dir_map.items():
        allowed, result = verify_skill(client, server, token, skill_dir, agent_id, skill_name)
        if allowed:
            active_names.append(result)

    _log(f"SessionStart: Active skills: {active_names}")
    if session_id:
        _set_active_skills_in_state(session_id, active_names)


# --------------------------------------------------------------------------- #
# ConfigChange handler (to update active skills)                              #
# --------------------------------------------------------------------------- #

def handle_config_change(event: dict, client: httpx.Client, server: str, token: str) -> None:
    """
    When config changes, verify the new skill and add to active skills.
    """
    session_id = event.get("session_id", "")
    file_path = event.get("file_path", "")
    agent_id = resolve_agent_id(session_id)

    if not file_path or not Path(file_path).name == "SKILL.md":
        return  # Not a skill file

    skill_dir = Path(file_path).parent
    skill_name = read_skill_name(skill_dir)
    if not skill_name:
        return

    allowed, result = verify_skill(client, server, token, skill_dir, agent_id, skill_name)
    if allowed:
        verified_name = result
        if session_id:
            current = _get_active_skills_from_state(session_id)
            if verified_name not in current:
                current.append(verified_name)
                _set_active_skills_in_state(session_id, current)
                _log(f"ConfigChange: Added {verified_name} to active skills: {current}")


# --------------------------------------------------------------------------- #
# PreToolUse handler                                                          #
# --------------------------------------------------------------------------- #

def handle_pre_tool_use(event: dict, client: httpx.Client, server: str, token: str) -> None:
    """
    Before every tool call, only verify active skills.
    """
    session_id = event.get("session_id", "")
    tool_name = event.get("tool_name", "")
    cwd = event.get("cwd", ".")
    agent_id = resolve_agent_id(session_id)

    # Get active skills from state
    active_skills = _get_active_skills_from_state(session_id) if session_id else []
    _log(f"PreToolUse: tool={tool_name}, active_skills={active_skills}")

    if not active_skills:
        _log("No active skills, allowing")
        return

    # Scan skill dirs to find locations of active skills
    skill_dir_map = _scan_skill_dirs(cwd)

    # Only verify active skills
    for skill_name in active_skills:
        if skill_name not in skill_dir_map:
            _log(f"Active skill {skill_name} not found in skill dirs, skipping")
            continue

        _log(f"Verifying active skill: {skill_name}")
        allowed, result = verify_skill(client, server, token, skill_dir_map[skill_name], agent_id, skill_name)
        if not allowed:
            _block(f"[agent-manager] {result}")

    # All active skills verified - allow
    _log("All active skills verified successfully")


def _block(reason: str) -> None:
    print(reason, file=sys.stderr)
    sys.exit(2)


# --------------------------------------------------------------------------- #
# Main dispatch                                                               #
# --------------------------------------------------------------------------- #

def main() -> None:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)  # Malformed input → allow (don't block on hook errors)

    try:
        server = resolve_server()
        token = resolve_token()

        with httpx.Client(timeout=30.0) as client:
            hook_event = event.get("hook_event_name", "")

            if hook_event == "SessionStart":
                handle_session_start(event, client, server, token)
            elif hook_event == "ConfigChange" and event.get("source") == "skills":
                handle_config_change(event, client, server, token)
            elif hook_event == "PreToolUse":
                handle_pre_tool_use(event, client, server, token)

        sys.exit(0)

    except SystemExit:
        raise
    except Exception as e:
        # Hook errors must not block the agent — log and continue
        error_msg = f"[agent-manager guard hook error] {e}"
        _log(error_msg)
        print(error_msg, file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
