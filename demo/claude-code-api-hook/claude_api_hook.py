"""
Claude Code API Hook — calls Agent Manager backend API to enforce skill registry.

Receives JSON events from Claude Code on stdin.
Sends events to Agent Manager backend API for processing.
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
      "SessionStart":  [{"matcher": "", "hooks": [{"type": "command", "command": "python3 /path/to/claude_api_hook.py"}]}],
      "ConfigChange":  [{"matcher": "skills", "hooks": [{"type": "command", "command": "python3 /path/to/claude_api_hook.py"}]}],
      "PreToolUse":    [{"matcher": "", "hooks": [{"type": "command", "command": "python3 /path/to/claude_api_hook.py"}]}]
    }
  }
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

# Try to load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def get_backend_url() -> str:
    """Get Agent Manager backend URL from environment or use default."""
    return os.environ.get(
        "AGENT_MANAGER_BASE_URL",
        "http://127.0.0.1:8080"
    ).rstrip("/")


def main() -> None:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)  # Malformed input → allow (don't block on hook errors)

    try:
        backend_url = get_backend_url()

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{backend_url}/api/v1/hook/event",
                json=event,
            )
            response.raise_for_status()
            result = response.json()

        allowed = result.get("allowed", True)
        message = result.get("message", "")

        if not allowed:
            print(message, file=sys.stderr)
            sys.exit(2)

        sys.exit(0)

    except Exception as e:
        # Hook errors must not block the agent — log and continue
        error_msg = f"[agent-manager api hook error] {e}"
        print(error_msg, file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
