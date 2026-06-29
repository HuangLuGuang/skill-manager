#!/usr/bin/env python3
"""Backward-compatible wrapper for the renamed Agent Manager Skill Verifier CLI."""

from agent_manager_skill_verifier import main


if __name__ == "__main__":
    raise SystemExit(main())
