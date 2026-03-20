"""
Runtime guard — enforces the registry at agent skill-load time.

Agents call can_load() before loading a skill and check_tool() before
invoking any tool. All decisions are logged to the audit trail.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .models import RegistryEntry, SkillStatus
from .registry import Registry, make_event
from .signer import verify_signature

logger = logging.getLogger(__name__)


class RuntimeGuard:
    """
    Enforces skill permissions at agent runtime.

    Usage::

        guard = RuntimeGuard()

        # Before loading a skill:
        allowed, entry, reason = guard.can_load("my-skill", "/path/to/skill", agent_id="agent-1")
        if not allowed:
            raise RuntimeError(reason)

        # Before invoking a tool:
        if not guard.check_tool("my-skill", "Bash", agent_id="agent-1"):
            raise PermissionError("Tool not permitted")
    """

    def __init__(self, registry: Registry | None = None):
        self.registry = registry or Registry()

    def can_load(
        self,
        skill_name: str,
        skill_path: str | None = None,
        agent_id: str | None = None,
        verify_sig: bool = True,
    ) -> tuple[bool, RegistryEntry | None, str]:
        """
        Check whether a skill may be loaded.

        Skills always live on the local filesystem — this method never fetches
        or serves skill content.  It only checks the registry and optionally
        verifies that the on-disk files match the approved signature.

        Three modes depending on the arguments:

        1. Name-only check  (skill_path=None)
           ──────────────────────────────────
           can_load("my-skill")

           Looks up the skill by name in the registry and checks that its
           status is APPROVED or DEPLOYED.  No filesystem access.  Use this
           when the skill directory is already trusted (e.g. it lives in a
           read-only company-controlled directory where only CI/CD can write).

        2. Name + signature verification  (skill_path provided)
           ──────────────────────────────────────────────────────
           can_load("my-skill", skill_path="/path/to/skill")

           Same as above, then recomputes the HMAC-SHA256 over the on-disk
           file tree and compares it to the signature stored at approval time.
           Blocks if any file was added, removed, or modified since approval.
           Use this when the skill directory is writable (developer workstation,
           shared network mount, etc.).

        3. Name-only despite path  (verify_sig=False)
           ────────────────────────────────────────────
           can_load("my-skill", skill_path="/path/to/skill", verify_sig=False)

           Checks the registry but skips signature verification even though a
           path was provided.  Useful for debugging or for environments where
           the directory protection is trusted as a substitute.

        Args:
            skill_name:  Name of the skill (must match registry entry name).
            skill_path:  Filesystem path to the skill directory.
                         Required for signature verification; ignored otherwise.
            agent_id:    Identifier of the loading agent (written to audit log).
            verify_sig:  If True (default) and skill_path is provided and the
                         registry entry has a stored signature, verify it.
                         If skill_path is None, this flag has no effect.

        Returns:
            (allowed: bool, entry: RegistryEntry | None, reason: str)
        """
        entry = self.registry.get_by_name(skill_name)

        if entry is None:
            reason = f"Skill {skill_name!r} is not in the registry"
            logger.warning("BLOCKED load: %s", reason)
            self._emit_blocked(skill_name, agent_id, reason)
            return False, None, reason

        if not entry.is_loadable():
            reason = f"Skill {skill_name!r} has status {entry.status.value} — only APPROVED/DEPLOYED skills may load"
            logger.warning("BLOCKED load: %s", reason)
            self._emit_blocked_entry(entry, agent_id, reason)
            return False, entry, reason

        if verify_sig and skill_path and entry.signature:
            if not verify_signature(skill_path, entry.signature):
                reason = f"Skill {skill_name!r} signature mismatch — possible tampering"
                logger.error("BLOCKED load (tamper): %s", reason)
                self._emit_blocked_entry(entry, agent_id, reason, tamper=True)
                return False, entry, reason

        logger.info("ALLOWED load: skill=%r agent=%r", skill_name, agent_id)
        self._emit_allowed(entry, agent_id)
        return True, entry, "allowed"

    def check_tool(
        self,
        skill_name: str,
        tool_name: str,
        agent_id: str | None = None,
    ) -> bool:
        """
        Check whether a skill is permitted to invoke a tool.

        Returns True if allowed, False if blocked.
        An empty allowed_tools list means all tools are permitted (skill made no
        declarations). This preserves backwards-compatibility with unmanaged skills
        that were approved before tool-level enforcement was introduced.
        """
        entry = self.registry.get_by_name(skill_name)

        if entry is None or not entry.is_loadable():
            self._emit_tool_blocked(skill_name, tool_name, agent_id, "skill not loadable")
            return False

        if not entry.allowed_tools:
            # No declarations — allow all (emit INFO-level log)
            logger.debug("Tool %r: no restrictions on skill %r", tool_name, skill_name)
            self._emit_tool_event(entry, tool_name, agent_id, allowed=True)
            return True

        allowed = tool_name in entry.allowed_tools
        if not allowed:
            reason = f"Tool {tool_name!r} not in declared allowed_tools for skill {skill_name!r}"
            logger.warning("BLOCKED tool: %s", reason)
            self._emit_tool_blocked(skill_name, tool_name, agent_id, reason)
        else:
            self._emit_tool_event(entry, tool_name, agent_id, allowed=True)

        return allowed

    def get_loadable_skills(self) -> list[RegistryEntry]:
        """Return all skills currently loadable by agents."""
        return self.registry.list_loadable()

    # ------------------------------------------------------------------ #
    # Audit helpers                                                        #
    # ------------------------------------------------------------------ #

    def _emit_allowed(self, entry: RegistryEntry, actor: str | None) -> None:
        self.registry.log_event(make_event(
            "skill_load_allowed", entry, actor=actor,
            details={"status": entry.status.value},
        ))

    def _emit_blocked(self, skill_name: str, actor: str | None, reason: str) -> None:
        from .models import AuditEvent
        import uuid
        from datetime import datetime, timezone
        ev = AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type="skill_load_blocked",
            skill_id="unknown",
            skill_name=skill_name,
            actor=actor,
            details={"reason": reason},
        )
        self.registry.log_event(ev)

    def _emit_blocked_entry(
        self, entry: RegistryEntry, actor: str | None, reason: str, tamper: bool = False
    ) -> None:
        event_type = "skill_tamper_detected" if tamper else "skill_load_blocked"
        self.registry.log_event(make_event(
            event_type, entry, actor=actor, details={"reason": reason},
        ))

    def _emit_tool_event(
        self, entry: RegistryEntry, tool: str, actor: str | None, allowed: bool
    ) -> None:
        event_type = "tool_invoked" if allowed else "tool_blocked"
        self.registry.log_event(make_event(
            event_type, entry, actor=actor, details={"tool": tool, "allowed": allowed},
        ))

    def _emit_tool_blocked(
        self, skill_name: str, tool: str, actor: str | None, reason: str
    ) -> None:
        from .models import AuditEvent
        import uuid
        ev = AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type="tool_blocked",
            skill_id="unknown",
            skill_name=skill_name,
            actor=actor,
            details={"tool": tool, "reason": reason},
        )
        self.registry.log_event(ev)
