#!/usr/bin/env python3
"""
Claude Code Agent Guard Hook - PreToolUse Only

Receives JSON events from Claude Code on stdin.
For PreToolUse events, verify the skill being called before allowing execution.

Hook events handled:
  PreToolUse     - verify the skill being called (if any)

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
import uuid
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
# Session state management (for caching verified skills)                     #
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


def _add_verified_skill(session_id: str, skill_name: str) -> None:
    """Add a verified skill to session state."""
    if not session_id:
        return
    state = _load_session_state(session_id)
    verified_skills = state.get("verified_skills", [])
    if skill_name not in verified_skills:
        verified_skills.append(skill_name)
        state["verified_skills"] = verified_skills
        _save_session_state(session_id, state)
        _log(f"Added verified skill: {skill_name}")


def _is_skill_verified(session_id: str, skill_name: str) -> bool:
    """Check if a skill has been verified in this session."""
    if not session_id:
        return False
    state = _load_session_state(session_id)
    verified_skills = state.get("verified_skills", [])
    return skill_name in verified_skills


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


def normalize_zip_mojibake(value: str) -> str:
    try:
        return value.encode("cp437").decode("utf-8")
    except UnicodeError:
        return value


def iter_skill_files(skill_dir: str | Path, ignores: set[str] | None = None) -> list[Path]:
    root = Path(skill_dir).resolve()
    ignored = ignores or set()
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in ignored for part in rel_parts):
            continue
        files.append(path)
    return sorted(
        files,
        key=lambda path: "/".join(
            normalize_zip_mojibake(part) for part in path.relative_to(root).parts
        ),
    )


def compute_skill_signature(skill_dir: str | Path, ignores: set[str] | None = None) -> str:
    root = Path(skill_dir).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    parts = []
    files = iter_skill_files(root, ignores=ignores or set())
    for path in files:
        rel = "/".join(normalize_zip_mojibake(part) for part in path.relative_to(root).parts)
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


def managed_skill_id(skill_dir: str | Path) -> str | None:
    """Return the platform skill UUID encoded in a managed install path."""
    roots = [_DEFAULT_BASE_DIR / "skills"]
    configured_root = os.environ.get("AGENT_MANAGER_MANAGED_SKILLS_DIR")
    if configured_root:
        roots.insert(0, Path(configured_root).expanduser())

    resolved = Path(skill_dir).resolve()
    for root in roots:
        try:
            relative = resolved.relative_to(root.resolve())
        except ValueError:
            continue
        if len(relative.parts) < 2:
            continue
        candidate = relative.parts[0]
        try:
            uuid.UUID(candidate)
        except ValueError:
            continue
        return candidate
    return None


# --------------------------------------------------------------------------- #
# API client - verify functionality only (with token)                        #
# --------------------------------------------------------------------------- #

def verify_skill_signature(
    client: httpx.Client,
    server: str,
    token: str,
    skill_dir: Path,
    skill_name: str | None = None,
    skill_id: str | None = None,
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
    if skill_id:
        body["skill_id"] = skill_id

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


def _format_block_message(reason: str, status: str | None = None) -> str:
    status_text = f" status={status}" if status else ""
    return f"阻断: {reason}{status_text}\n不要调用该 Skill。请联系管理员在 Agent Manager 中审批通过后再使用。"


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
            return False, f"无法识别 Skill 名称。请确认目录包含带 name 的 SKILL.md"

    try:
        skill_id = managed_skill_id(skill_dir)
        if skill_id:
            _log(f"Managed Skill ID: {skill_id} for {skill_dir}")

        # Step 1: Verify signature
        verify_result = verify_skill_signature(
            client,
            server,
            token,
            skill_dir,
            skill_name=skill_name,
            skill_id=skill_id,
            agent_id=agent_id,
            ignores=DEFAULT_IGNORES,
        )
        if not verify_result.get("allowed"):
            reason = verify_result.get("reason") or "内容完整性校验失败"
            status = verify_result.get("status")
            return False, _format_block_message(str(reason), status)

        verified_name = verify_result.get("skill_name") or skill_name
        if not verified_name:
            return False, _format_block_message("平台未返回 Skill 名称，无法继续加载校验", verify_result.get("status"))

        if verify_result.get("status") != "APPROVED":
            return False, _format_block_message("Skill 尚未审批通过", verify_result.get("status"))

        # Step 2: Check can-load
        verified_ref = verify_result.get("skill_id") or skill_id or verified_name
        can_load_result = can_load_skill(client, server, token, verified_ref, agent_id)
        if not can_load_result.get("allowed"):
            reason = can_load_result.get("reason") or "状态不允许加载"
            status = can_load_result.get("status")
            return False, _format_block_message(str(reason), status)

        if can_load_result.get("status") != "APPROVED":
            return False, _format_block_message("Skill 尚未审批通过", can_load_result.get("status"))

        return True, verified_name

    except httpx.HTTPStatusError as e:
        _log(f"API error verifying skill {skill_name}: {e}")
        try:
            detail = e.response.text
        except Exception:
            detail = str(e)
        return False, _format_block_message(f"Agent Manager API 返回 {e.response.status_code}: {detail}")
    except httpx.HTTPError as e:
        _log(f"API error verifying skill {skill_name}: {e}")
        return False, _format_block_message(f"无法连接 Agent Manager: {e}")


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
                # Candidate roots are ordered by priority; keep the first match.
                skill_dir_map.setdefault(name, skill_md.parent)
    return skill_dir_map


def _extract_skill_name_from_event(event: dict) -> str | None:
    """
    Extract skill name from PreToolUse event.
    Looking for Skill tool calls with skill name in args.
    """
    tool_name = event.get("tool_name", "")
    if tool_name != "Skill":
        return None

    # Try to extract skill name from tool_input
    tool_input = event.get("tool_input", {})
    if isinstance(tool_input, dict):
        # 兼容 Claude Code and Trae IDE
        skill_name = tool_input.get("skill", None) or tool_input.get("name", None)
        if skill_name:
            return skill_name

    # Try to extract skill name from args (fallback)
    args = event.get("args", {})
    if isinstance(args, dict):
        skill_name = args.get("skill")
        if skill_name:
            return skill_name

    # Fallback: try to parse args as string
    args_str = event.get("args_str", "")
    if args_str:
        # Simple heuristic: first word is skill name
        parts = args_str.strip().split()
        if parts:
            return parts[0]

    return None


# --------------------------------------------------------------------------- #
# PreToolUse handler (only one we need)                                      #
# --------------------------------------------------------------------------- #

def _find_project_root(current_dir: str) -> str:
    """Find project root by looking for .git or .claude directory."""
    path = Path(current_dir).resolve()
    for parent in [path] + list(path.parents):
        if (parent / ".git").exists() or (parent / ".claude").exists():
            return str(parent)
    return current_dir


def handle_pre_tool_use(event: dict, client: httpx.Client, server: str, token: str) -> None:
    """
    Before every tool call:
    - If it's a Skill tool call: verify the skill being called
    - Otherwise: allow
    """
    session_id = event.get("session_id", "")
    tool_name = event.get("tool_name", "")
    cwd = event.get("cwd", ".")
    agent_id = resolve_agent_id(session_id)

    _log(f"PreToolUse: tool={tool_name}")

    # Only verify Skill tool calls
    if tool_name != "Skill":
        _log("Not a Skill tool call, allowing")
        return

    # Extract skill name from event
    skill_name = _extract_skill_name_from_event(event)
    if not skill_name:
        _log("Could not extract skill name from event, allowing")
        return

    _log(f"Skill being called: {skill_name}")

    # Find project root (cwd might already be in skill directory)
    project_root = _find_project_root(cwd)
    _log(f"Project root: {project_root}")

    # Scan skill dirs to find the skill
    skill_dir_map = _scan_skill_dirs(project_root)
    if skill_name not in skill_dir_map:
        _block(_format_block_message(f"Skill {skill_name!r} not found in skill directories"))
        return

    skill_dir = skill_dir_map[skill_name]
    _log(f"Found skill directory: {skill_dir}")

    # Verify the skill
    allowed, result = verify_skill(client, server, token, skill_dir, agent_id, skill_name)
    if not allowed:
        _block(result)
        return

    # Verification passed - cache it and allow
    _log(f"Skill {result!r} verified successfully")
    _add_verified_skill(session_id, result)


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

    hook_event = event.get("hook_event_name", "")
    skill_name = _extract_skill_name_from_event(event) if hook_event == "PreToolUse" else None
    if hook_event != "PreToolUse" or not skill_name:
        sys.exit(0)

    try:
        server = resolve_server()
        token = resolve_token()

        with httpx.Client(timeout=30.0) as client:
            handle_pre_tool_use(event, client, server, token)

        sys.exit(0)

    except SystemExit:
        raise
    except Exception as e:
        error_msg = f"[agent-manager guard hook error] {e}"
        _log(error_msg)
        _block(_format_block_message(error_msg))


if __name__ == "__main__":
    main()
